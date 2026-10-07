"""Orchestrates feature-doc generation end to end.

Builds the skeleton, discovers features (mapper), decides what to
(re)generate per the preserve/stale policy — a human-authored page's content
is never overwritten; if its members_hash has drifted since the edit it is
marked `stale` instead — generates missing/changed docs (generator), syncs
both stores (store.py), and exports the bundle. This is what `cvg-docs-build`,
`cvg-ingest --docs`, and the dashboard's "Generate docs" button all call.
"""

from __future__ import annotations

import hashlib
import logging
from datetime import datetime, timezone
from pathlib import Path

from code_vector_graph.ingestion.okf import cache as okf_cache
from code_vector_graph.ingestion.okf.features.generator import generate_feature_doc
from code_vector_graph.ingestion.okf.features.inventory import build_inventory
from code_vector_graph.ingestion.okf.features.mapper import discover_features
from code_vector_graph.ingestion.okf.features.models import (
    FeatureBuildDeps,
    FeatureBuildRequest,
    FeatureBuildResult,
    FeatureFrontmatter,
    FeatureMap,
    FeaturePage,
    FeatureSpec,
    FileInventory,
)
from code_vector_graph.ingestion.okf.features.store import (
    delete_feature,
    feature_id_for,
    load_existing_features,
    sync_features_neo4j,
    sync_features_qdrant,
)
from code_vector_graph.ingestion.okf.features.template import compose_page
from code_vector_graph.ingestion.okf.skeleton import build_skeleton

logger = logging.getLogger(__name__)

FEATURE_MAP_FILENAME = ".okf-features.json"
FEATURE_DOC_CACHE_FILENAME = ".okf-features-cache.json"


def _members_hash(spec: FeatureSpec, inventory: list[FileInventory]) -> str:
    by_path = {f.rel_path: f for f in inventory}
    hashes = sorted(by_path[p].concept_hash for p in spec.member_files if p in by_path)
    return hashlib.sha256("|".join(hashes).encode("utf-8")).hexdigest()[:16]


def _load_prior_map(bundle_dir: str | None) -> FeatureMap | None:
    if not bundle_dir:
        return None
    path = Path(bundle_dir) / FEATURE_MAP_FILENAME
    if not path.exists():
        return None
    try:
        return FeatureMap.model_validate_json(path.read_text(encoding="utf-8"))
    except Exception as exc:  # malformed/legacy file — a fresh map is safe, just less stable
        logger.warning("Ignoring unreadable prior feature map %s: %s", path, exc)
        return None


def build_feature_docs(req: FeatureBuildRequest, deps: FeatureBuildDeps) -> FeatureBuildResult:
    result = FeatureBuildResult()
    now = datetime.now(timezone.utc).isoformat()

    skeleton = build_skeleton(req.repo_path)
    doc_summary_cache = okf_cache.load_cache(req.bundle_dir) if req.bundle_dir else {}
    inventory = build_inventory(skeleton, doc_summary_cache)
    if not inventory:
        result.warnings.append("No files found to document (empty repo, or all files excluded from enrichment).")
        return result

    prior_map = _load_prior_map(req.bundle_dir)
    existing = load_existing_features(deps.graph_store, req.app, req.repo_name) if deps.graph_store else {}

    feature_map, map_warnings = discover_features(
        deps.llm_client, req.model_map, inventory,
        app=req.app, repo=req.repo_name, prior=prior_map, dry_run=req.dry_run,
    )
    result.warnings.extend(map_warnings)
    result.features = len(feature_map.features)
    generated_slugs = {spec.slug for spec in feature_map.features}

    feature_doc_cache = okf_cache.load_cache(req.bundle_dir, filename=FEATURE_DOC_CACHE_FILENAME) if req.bundle_dir else {}
    new_doc_cache: dict[str, dict] = {}
    # An LLM-authored page we're about to (re)generate will need embedding;
    # if no embedder is available this run, flag it so a later
    # `cvg-docs-build --reembed-pending` (or the next full build) catches up.
    embedder_unavailable = deps.vector_store is not None and deps.embedder is None

    pages: list[FeaturePage] = []
    reembed_pages: list[FeaturePage] = []
    member_labels: dict[str, str] = {}

    for spec in feature_map.features:
        if req.only_slugs and spec.slug not in req.only_slugs:
            continue  # not selected this run — leave its Neo4j/bundle state untouched

        new_hash = _members_hash(spec, inventory)
        member_set = set(spec.member_files)
        member_ids = [f.file_id for f in inventory if f.rel_path in member_set]
        for f in inventory:
            if f.rel_path in member_set:
                member_labels[f.file_id] = "File"

        fid = feature_id_for(req.app, req.repo_name, spec.slug)
        prior_existing = existing.get(spec.slug)

        if prior_existing is not None and prior_existing.source == "human":
            # Never overwritten: keep every human-visible field (title, body,
            # description, kind, tags, timestamps) exactly as-is. Only the
            # bookkeeping fields that must track the current code refresh:
            # members_hash/member_files/member_ids (for the IMPLEMENTED_BY
            # edges) and the derived stale/stale_since.
            baseline = prior_existing.edited_members_hash or prior_existing.members_hash
            is_stale = new_hash != baseline
            if is_stale and not prior_existing.stale:
                stale_since = now
            elif not is_stale:
                stale_since = None
            else:
                stale_since = prior_existing.stale_since
            fm = FeatureFrontmatter(
                title=prior_existing.title or spec.title,
                slug=spec.slug,
                description=prior_existing.description or spec.description,
                app=req.app, repo=req.repo_name, feature_id=fid,
                kind=prior_existing.kind or spec.kind,
                members_hash=new_hash, member_files=spec.member_files, member_ids=member_ids,
                source="human", stale=is_stale, stale_since=stale_since,
                generated_at=prior_existing.generated_at or now,
                edited_at=prior_existing.edited_at,
                edited_members_hash=baseline,
                model=None, language=req.language,
                tags=prior_existing.tags or spec.tags,
            )
            pages.append(FeaturePage(fm=fm, body=prior_existing.content))
            result.kept_human += 1
            if is_stale:
                result.stale += 1
            continue

        cache_key = f"{spec.slug}:{new_hash}"
        if not req.force and cache_key in feature_doc_cache:
            body = feature_doc_cache[cache_key]["body"]
            new_doc_cache[cache_key] = feature_doc_cache[cache_key]
            result.cached += 1
        else:
            body, _used_fallback, gen_warnings = generate_feature_doc(
                deps.llm_client, req.model_doc, spec, skeleton, inventory, language=req.language,
            )
            result.warnings.extend(gen_warnings)
            new_doc_cache[cache_key] = {"body": body}
            result.generated += 1

        fm = FeatureFrontmatter(
            title=spec.title, slug=spec.slug, description=spec.description,
            app=req.app, repo=req.repo_name, feature_id=fid, kind=spec.kind,
            members_hash=new_hash, member_files=spec.member_files, member_ids=member_ids,
            source="llm", stale=False, stale_since=None, generated_at=now,
            edited_at=None, edited_members_hash=None, model=req.model_doc,
            language=req.language, tags=spec.tags, needs_reembed=embedder_unavailable,
        )
        page = FeaturePage(fm=fm, body=body)
        pages.append(page)
        reembed_pages.append(page)

    # Orphans: an existing feature no longer produced by this run's map.
    if not req.only_slugs:
        for slug, ex in existing.items():
            if slug in generated_slugs:
                continue
            if ex.source == "human":
                fm = FeatureFrontmatter(
                    title=ex.title or slug, slug=slug, description=ex.description,
                    app=req.app, repo=req.repo_name, feature_id=ex.feature_id, kind=ex.kind,
                    members_hash="0" * 16, member_files=[], member_ids=[],
                    source="human", stale=True, stale_since=ex.stale_since or now,
                    generated_at=ex.generated_at or now, edited_at=ex.edited_at,
                    edited_members_hash=ex.edited_members_hash, model=None,
                    language=req.language, tags=ex.tags,
                )
                pages.append(FeaturePage(fm=fm, body=ex.content))
                result.warnings.append(
                    f"Feature '{slug}' no longer maps to any files; kept (human-authored) and marked stale."
                )
            else:
                if deps.graph_store is not None or deps.vector_store is not None:
                    delete_feature(deps.graph_store, deps.vector_store, ex.wiki_id, ex.feature_id)
                result.deleted += 1

    if deps.graph_store is not None and pages:
        sync_features_neo4j(pages, member_labels, req.repo_id, deps.graph_store)

    if reembed_pages:
        if deps.vector_store is not None and deps.embedder is not None:
            qstats = sync_features_qdrant(
                reembed_pages, deps.embedder, deps.vector_store, deps.tokenizer_name or "bert-base-uncased"
            )
            result.chunks += qstats.get("chunks", 0)
        elif deps.vector_store is not None:
            result.needs_reembed += len(reembed_pages)

    if req.bundle_dir:
        _write_bundle_exports(req, feature_map, pages, new_doc_cache)

    return result


def _write_bundle_exports(
    req: FeatureBuildRequest,
    feature_map: FeatureMap,
    pages: list[FeaturePage],
    new_doc_cache: dict[str, dict],
) -> None:
    """Write the human-visible `feature/*.md` preview unconditionally (same
    convention as `cvg-okf-build --dry-run`: metadata/fallback pages, but a
    real bundle on disk); persist the map + doc cache only on a real run, so
    a dry-run's structural map never pollutes future slug-reuse/caching.
    """
    bundle_dir = Path(req.bundle_dir)
    bundle_dir.mkdir(parents=True, exist_ok=True)
    if not req.dry_run:
        (bundle_dir / FEATURE_MAP_FILENAME).write_text(feature_map.model_dump_json(indent=2), encoding="utf-8")
        okf_cache.save_cache(str(bundle_dir), new_doc_cache, filename=FEATURE_DOC_CACHE_FILENAME)

    feature_dir = bundle_dir / "feature"
    feature_dir.mkdir(parents=True, exist_ok=True)
    for page in pages:
        (feature_dir / f"{page.fm.slug}.md").write_text(compose_page(page.fm, page.body), encoding="utf-8")

    if req.only_slugs:
        # A partial run only ever adds/updates files for the slugs it
        # touched — deleting orphans or rewriting the index needs the full
        # picture, which a partial run doesn't have.
        return

    written = {f"{page.fm.slug}.md" for page in pages}
    for existing_file in feature_dir.glob("*.md"):
        if existing_file.name != "index.md" and existing_file.name not in written:
            existing_file.unlink()

    index_lines = ["# Features", ""]
    for page in sorted(pages, key=lambda p: p.fm.title.lower()):
        index_lines.append(f"- [{page.fm.title}](/feature/{page.fm.slug}.md)")
    (feature_dir / "index.md").write_text("\n".join(index_lines) + "\n", encoding="utf-8")
