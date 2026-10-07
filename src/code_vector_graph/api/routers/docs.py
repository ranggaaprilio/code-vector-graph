"""Doc-page endpoints: list/detail, validate, create, edit (PUT), reindex,
delete, regenerate, and trigger a full "Generate docs" build for an
application.

Two kinds of ``WikiPage`` live behind these routes: LLM-authored **Feature**
pages (the original subsystem — generated/edited/regenerated, template
8-section body) and human-authored **Document** pages (free-form Markdown,
created directly by a person via the dashboard, never touched by "Generate
docs"). Reuses the scope/query helpers from `apps.py` (same `/apps` prefix)
and the already-tested `ingestion/okf/features` pipeline for validation,
generation, and store writes — this module is orchestration/HTTP plumbing
only.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query

from code_vector_graph.api.deps import (
    get_docs_jobs,
    get_embedder,
    get_graph,
    get_llm_client,
    get_registry,
    get_vector_store,
)
from code_vector_graph.api.config import MODEL_ID
from code_vector_graph.api.routers.apps import _count, _query, _scope_or_404
from code_vector_graph.api.schemas import (
    DocsGenerateRequest,
    DocumentCreate,
    FeatureDocUpdate,
    MarkdownValidateRequest,
)
from code_vector_graph.api.serialize import node_props, record_get
from code_vector_graph.api.services.apps import ApplicationRegistry
from code_vector_graph.config import CVG_DOCS_BUNDLE_DIR, CVG_DOCS_LANGUAGE, MODEL_CONFIGS, OKF_FEATURES_MODEL
from code_vector_graph.ingestion.okf.features.documents import (
    document_id_for,
    document_page_from_props,
    delete_document,
    existing_document_slugs,
    extract_mentioned_paths,
    mark_reembedded,
    remove_document_bundle_file,
    resolve_mentions,
    save_document_page,
    set_mentions,
    slugify,
    sync_document_neo4j,
    sync_document_qdrant,
    unique_slug,
    word_count,
    write_document_bundle_file,
)
from code_vector_graph.ingestion.okf.features.generator import generate_feature_doc
from code_vector_graph.ingestion.okf.features.inventory import build_inventory
from code_vector_graph.ingestion.okf.features.models import (
    DocumentFrontmatter,
    DocumentPage,
    FeatureBuildDeps,
    FeatureBuildRequest,
    FeatureFrontmatter,
    FeaturePage,
    FeatureSpec,
    FileInventory,
    ValidationIssue,
    ValidationResult,
)
from code_vector_graph.ingestion.okf.features.store import save_feature_page, sync_features_qdrant
from code_vector_graph.ingestion.okf.features.template import compose_page, extract_title, first_paragraph, parse_sections
from code_vector_graph.ingestion.okf.features.validate import validate_document_body, validate_feature_body
from code_vector_graph.ingestion.okf.features.build import build_feature_docs
from code_vector_graph.ingestion.okf.skeleton import Skeleton, build_skeleton
from code_vector_graph.ingestion.okf.sync import wiki_id
from code_vector_graph.repos import RepoIdentity

router = APIRouter(prefix="/apps")
logger = logging.getLogger(__name__)

# A document's index job runs on this fixed stage sequence — reused by
# create/update/reindex so the frontend's progress stepper is consistent.
_DOCUMENT_INDEX_STAGES = ("linking_mentions", "embedding", "upserting_vectors", "writing_bundle", "done")


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #


def _result_to_dict(result: ValidationResult) -> dict[str, Any]:
    def _issue(i: ValidationIssue) -> dict[str, Any]:
        return {"code": i.code, "message": i.message, "line": i.line}

    return {"ok": result.ok, "errors": [_issue(e) for e in result.errors], "warnings": [_issue(w) for w in result.warnings]}


def _doc_row(rec) -> dict[str, Any]:
    return {
        "feature_id": record_get(rec, "feature_id"),
        "slug": record_get(rec, "slug"),
        "title": record_get(rec, "title"),
        "summary": record_get(rec, "summary"),
        "type": record_get(rec, "type") or "Feature",
        "kind": record_get(rec, "kind"),
        "category": record_get(rec, "category"),
        "repo": record_get(rec, "repo"),
        "source": record_get(rec, "source"),
        "stale": bool(record_get(rec, "stale") or False),
        "member_count": len(record_get(rec, "member_files") or []),
        "mention_count": int(record_get(rec, "mention_count") or 0),
        "word_count": record_get(rec, "word_count"),
        "tags": record_get(rec, "tags") or [],
        "generated_at": record_get(rec, "generated_at"),
        "created_at": record_get(rec, "created_at"),
        "edited_at": record_get(rec, "edited_at"),
        "needs_reembed": bool(record_get(rec, "needs_reembed") or False),
    }


def _fetch_page(graph, app: str, page_id: str, *, types: tuple[str, ...] = ("Feature",)) -> dict[str, Any] | None:
    recs = _query(
        graph,
        "MATCH (w:WikiPage) WHERE (w.concept_id = $cid OR w.id = $cid) AND w.app = $app AND w.type IN $types RETURN w",
        {"cid": page_id, "app": app, "types": list(types)},
        what="doc lookup",
    )
    if not recs:
        return None
    return node_props(record_get(recs[0], "w")) or None


def _frontmatter_from_props(props: dict[str, Any]) -> FeatureFrontmatter:
    return FeatureFrontmatter(
        title=props.get("title") or props.get("slug") or "Untitled",
        slug=props.get("slug") or "feature",
        description=props.get("summary") or "",
        app=props.get("app") or "",
        repo=props.get("repo") or "",
        feature_id=props.get("concept_id") or "",
        kind=props.get("kind") or "other",
        members_hash=props.get("members_hash") or "0" * 16,
        member_files=list(props.get("member_files") or []),
        member_ids=[],
        source=props.get("source") or "llm",
        stale=bool(props.get("stale") or False),
        stale_since=props.get("stale_since"),
        generated_at=props.get("generated_at") or "",
        edited_at=props.get("edited_at"),
        edited_members_hash=props.get("edited_members_hash"),
        model=props.get("model"),
        language=props.get("language") or "en",
        tags=list(props.get("tags") or []),
        needs_reembed=bool(props.get("needs_reembed") or False),
    )


def _maybe_write_bundle_file(props: dict[str, Any]) -> bool:
    """Best-effort mirror of a saved edit onto the OKF bundle on disk, so a
    `cvg-reinit-graph --clear` + `cvg-okf-sync` can restore it later. A missing
    bundle directory on this host (the common case for the API server) is not
    an error — Neo4j remains the source of truth."""
    feature_dir = Path(CVG_DOCS_BUNDLE_DIR) / "feature"
    if not feature_dir.is_dir():
        return False
    try:
        fm = _frontmatter_from_props(props)
        (feature_dir / f"{fm.slug}.md").write_text(compose_page(fm, props.get("content") or ""), encoding="utf-8")
        return True
    except Exception:
        logger.warning("Failed to write bundle file for feature '%s'", props.get("slug"), exc_info=True)
        return False


def _graph_only_inventory(member_files: list[str]) -> list[FileInventory]:
    """A source-less inventory built purely from member file paths, used when
    the repo isn't readable from this host — the LLM still gets the feature's
    description/member list, just no code excerpts."""
    out = []
    for path in member_files:
        top_dir = path.split("/", 1)[0] if "/" in path else "."
        out.append(FileInventory(file_id="", path=path, rel_path=path, language="", top_dir=top_dir))
    return out


def _index_document_vectors(page: DocumentPage, report, vector_store, embedder, graph) -> tuple[int, bool]:
    """Embed+upsert a Document page's chunks, reporting progress as it goes.

    Returns ``(chunks_written, needs_reembed)``. Never raises for a missing
    embedder/vector_store — that is a normal, recoverable state (the page
    stays flagged ``needs_reembed`` until a later Reindex catches it up).
    """
    if vector_store is None:
        return 0, False
    if embedder is None:
        report("embedding", message="No embedder configured on this server — search index pending.")
        return 0, True

    tokenizer_name = MODEL_CONFIGS[MODEL_ID]["tokenizer_name"]
    stats = sync_document_qdrant(
        page, embedder, vector_store, tokenizer_name,
        report=lambda done, total: report("embedding", done=done, total=total),
    )
    report("upserting_vectors")
    mark_reembedded(graph, page.fm.doc_id)
    return stats.get("chunks", 0), False


def _target_for_scope(app: str, repo_info) -> tuple[str, str]:
    """The node a Document's `DOCUMENTS` edge points at: the chosen Repository,
    or the Application when no repo was chosen (an app-level document)."""
    if repo_info is not None:
        return RepoIdentity(app=app, name=repo_info.name, root=repo_info.root).id, "Repository"
    return RepoIdentity(app=app, name="", root="").app_id, "Application"


_EMPTY_SKELETON = Skeleton(repo_path="", nodes={}, concept_ids=[], id_to_path={}, name_to_id={}, contains={}, files=[])


# --------------------------------------------------------------------------- #
# endpoints — order matters only within the SAME HTTP method + path-segment
# count: literal paths ("validate", "generate", "jobs", "jobs/{id}") must be
# registered before the generic "/{page_id}" GET route they'd otherwise
# shadow. Different methods (POST/PUT/DELETE) on differently-shaped paths
# never collide, so their relative order is free.
# --------------------------------------------------------------------------- #


@router.get("/{app}/docs")
def list_docs(
    app: str,
    repo: str = Query(default=""),
    q: str = Query(default=""),
    stale: bool | None = Query(default=None),
    source: str = Query(default=""),
    kind: str = Query(default=""),
    type: str = Query(default="Feature", pattern="^(Feature|Document|all)$"),
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    registry: ApplicationRegistry = Depends(get_registry),
    graph=Depends(get_graph),
):
    scope = _scope_or_404(registry, app, repo)
    where, params = scope.cypher_wiki_where("w")
    params.update(
        q=(q or "").strip().lower() or None,
        stale=stale,
        source=source or None,
        kind=kind or None,
        type=None if type == "all" else type,
        limit=limit,
        offset=offset,
    )
    filters = (
        f"{where} AND w.type IN ['Feature','Document'] "
        "AND ($type IS NULL OR w.type = $type) "
        "AND ($q IS NULL OR toLower(coalesce(w.title,'')) CONTAINS $q OR toLower(coalesce(w.summary,'')) CONTAINS $q) "
        "AND ($stale IS NULL OR w.stale = $stale) "
        "AND ($source IS NULL OR w.source = $source) "
        "AND ($kind IS NULL OR w.type <> 'Feature' OR w.kind = $kind)"
    )
    total = _count(graph, f"MATCH (w:WikiPage) WHERE {filters} RETURN count(w) AS n", params, what="docs total")
    rows = [
        _doc_row(rec)
        for rec in _query(
            graph,
            f"MATCH (w:WikiPage) WHERE {filters} "
            "RETURN w.concept_id AS feature_id, w.slug AS slug, w.title AS title, w.summary AS summary, "
            "w.type AS type, w.kind AS kind, w.category AS category, w.repo AS repo, w.source AS source, "
            "w.stale AS stale, w.member_files AS member_files, size(coalesce(w.mentions, [])) AS mention_count, "
            "w.word_count AS word_count, w.tags AS tags, w.generated_at AS generated_at, "
            "w.created_at AS created_at, w.edited_at AS edited_at, w.needs_reembed AS needs_reembed "
            "ORDER BY w.stale DESC, w.title SKIP $offset LIMIT $limit",
            params,
            what="docs list",
        )
    ]
    return {"features": rows, "total": total, "limit": limit, "offset": offset, "scope": scope.label}


@router.post("/{app}/docs", status_code=202)
def create_doc(
    app: str,
    body: DocumentCreate,
    registry: ApplicationRegistry = Depends(get_registry),
    graph=Depends(get_graph),
    vector_store=Depends(get_vector_store),
    embedder=Depends(get_embedder),
    jobs=Depends(get_docs_jobs),
):
    scope = _scope_or_404(registry, app, body.repo or None)
    repo_info = scope.repos[0] if body.repo else None

    markdown = body.markdown
    if extract_title(markdown) is None and body.title and body.title.strip():
        markdown = f"# {body.title.strip()}\n\n{markdown.strip()}\n"

    title = extract_title(markdown)
    result = validate_document_body(markdown, title=title)
    if not result.ok:
        raise HTTPException(status_code=422, detail={"validation": _result_to_dict(result)})

    slug = unique_slug(slugify(title), existing_document_slugs(graph, app, body.repo))
    doc_id = document_id_for(app, body.repo, slug)
    if jobs.is_running(app, "index_document", key=doc_id):
        raise HTTPException(status_code=409, detail="This document is already being indexed.")

    now = datetime.now(timezone.utc).isoformat()
    fm = DocumentFrontmatter(
        title=title, slug=slug, description=first_paragraph(markdown), app=app, repo=body.repo, doc_id=doc_id,
        category=body.category, tags=list(body.tags), created_at=now, word_count=word_count(markdown),
        source_file=body.source_file, needs_reembed=True,
    )
    page = DocumentPage(fm=fm, body=markdown)
    target_id, target_label = _target_for_scope(app, repo_info)

    def _run(report) -> dict[str, Any]:
        report("saving_graph")
        sync_document_neo4j(page, [], target_id=target_id, target_label=target_label, graph_store=graph)
        report("linking_mentions")
        mentions = resolve_mentions(graph, scope, extract_mentioned_paths(markdown))
        set_mentions(graph, doc_id, mentions)
        chunks, needs_reembed = _index_document_vectors(page, report, vector_store, embedder, graph)
        report("writing_bundle")
        write_document_bundle_file(page, CVG_DOCS_BUNDLE_DIR)
        return {"doc_id": doc_id, "slug": slug, "chunks": chunks, "mentions": len(mentions), "needs_reembed": needs_reembed}

    job_id = jobs.start(
        app, body.repo, _run, kind="index_document", key=doc_id,
        stages=("saving_graph",) + _DOCUMENT_INDEX_STAGES,
        target={"doc_id": doc_id, "slug": slug, "title": title},
    )
    return {"job_id": job_id, "doc_id": doc_id, "slug": slug, "status": "queued"}


@router.post("/{app}/docs/validate")
def validate_doc(app: str, body: MarkdownValidateRequest):
    if body.type == "Document":
        return _result_to_dict(validate_document_body(body.markdown, title=body.title))
    return _result_to_dict(validate_feature_body(body.markdown, title=body.title))


@router.post("/{app}/docs/generate", status_code=202)
def generate_docs(
    app: str,
    body: DocsGenerateRequest,
    registry: ApplicationRegistry = Depends(get_registry),
    graph=Depends(get_graph),
    vector_store=Depends(get_vector_store),
    embedder=Depends(get_embedder),
    llm_client=Depends(get_llm_client),
    jobs=Depends(get_docs_jobs),
):
    scope = _scope_or_404(registry, app, body.repo or None)
    if jobs.is_running(app):
        raise HTTPException(status_code=409, detail="A docs build is already running for this application.")

    accessible = [r for r in scope.repos if r.root and Path(r.root).is_dir()]
    if not accessible:
        example_root = scope.repos[0].root if scope.repos else "<repo-path>"
        raise HTTPException(
            status_code=409,
            detail={
                "error": "repo_not_accessible",
                "message": "No repository root for this application is accessible from the API server.",
                "hint": f"cvg-docs-build --repo-path {example_root} --app-name {app}",
            },
        )

    tokenizer_name = MODEL_CONFIGS[MODEL_ID]["tokenizer_name"]
    n = len(accessible)

    def _run(report) -> dict[str, Any]:
        totals = {
            "features": 0, "generated": 0, "cached": 0, "kept_human": 0,
            "stale": 0, "deleted": 0, "chunks": 0, "needs_reembed": 0, "warnings": [],
        }
        for i, repo_info in enumerate(accessible, start=1):
            report("generating", message=f"{repo_info.name} ({i}/{n})", done=i - 1, total=n)
            req = FeatureBuildRequest(
                repo_path=repo_info.root, app=app, repo_name=repo_info.name,
                repo_id=RepoIdentity(app=app, name=repo_info.name, root=repo_info.root).id,
                bundle_dir=CVG_DOCS_BUNDLE_DIR, language=CVG_DOCS_LANGUAGE,
                model_map=OKF_FEATURES_MODEL, model_doc=OKF_FEATURES_MODEL, force=body.force,
            )
            deps = FeatureBuildDeps(
                llm_client=llm_client, graph_store=graph, vector_store=vector_store,
                embedder=embedder, tokenizer_name=tokenizer_name,
            )
            result = build_feature_docs(req, deps)
            for key in ("features", "generated", "cached", "kept_human", "stale", "deleted", "chunks", "needs_reembed"):
                totals[key] += getattr(result, key)
            totals["warnings"].extend(result.warnings)
        report("generating", done=n, total=n)
        registry.list(refresh=True)
        return totals

    job_id = jobs.start(app, body.repo, _run, stages=("generating", "done"))
    return {"job_id": job_id, "status": "queued"}


@router.get("/{app}/docs/jobs")
def get_latest_docs_job(app: str, jobs=Depends(get_docs_jobs)):
    job = jobs.latest(app)
    if job is None:
        raise HTTPException(status_code=404, detail="No docs build has been run for this application yet.")
    return job.to_dict()


@router.get("/{app}/docs/jobs/{job_id}")
def get_docs_job(app: str, job_id: str, jobs=Depends(get_docs_jobs)):
    job = jobs.get(job_id)
    if job is None or job.app != app:
        raise HTTPException(status_code=404, detail=f"Job '{job_id}' not found")
    return job.to_dict()


@router.get("/{app}/docs/{page_id}")
def get_doc(
    app: str,
    page_id: str,
    registry: ApplicationRegistry = Depends(get_registry),
    graph=Depends(get_graph),
    jobs=Depends(get_docs_jobs),
):
    scope = _scope_or_404(registry, app)
    props = _fetch_page(graph, app, page_id, types=("Feature", "Document"))
    if not props:
        raise HTTPException(status_code=404, detail=f"Page '{page_id}' not found")

    is_document = props.get("type") == "Document"
    members: list[dict] = []
    mentions: list[dict] = []
    indexing_job: dict[str, Any] | None = None

    if is_document:
        doc_id = props.get("concept_id") or page_id
        mentions = [
            {
                "id": record_get(r, "id"), "path": record_get(r, "path"), "rel_path": record_get(r, "rel_path"),
                "repo": record_get(r, "repo"), "token": record_get(r, "token"),
            }
            for r in _query(
                graph,
                "MATCH (w:WikiPage {type:'Document'}) WHERE w.concept_id = $cid OR w.id = $cid "
                "MATCH (w)-[r:MENTIONS]->(f:File) "
                "RETURN f.id AS id, f.path AS path, f.rel_path AS rel_path, f.repo AS repo, r.path AS token "
                "ORDER BY token",
                {"cid": page_id},
                what="document mentions",
            )
        ]
        job = jobs.latest_for(app, "index_document", key=doc_id)
        indexing_job = job.to_dict() if job is not None else None
    else:
        members = [
            {
                "id": record_get(r, "id"), "label": record_get(r, "label"), "role": record_get(r, "role"),
                "name": record_get(r, "name"), "file_path": record_get(r, "file_path"),
                "start_line": record_get(r, "start_line"),
            }
            for r in _query(
                graph,
                "MATCH (w:WikiPage {type:'Feature'}) WHERE w.concept_id = $cid OR w.id = $cid "
                "MATCH (w)-[r:IMPLEMENTED_BY]->(n) OPTIONAL MATCH (n)<-[:CONTAINS|DEFINES]-(f:File) "
                "RETURN n.id AS id, labels(n)[0] AS label, r.role AS role, "
                "coalesce(n.name, n.path) AS name, coalesce(n.path, f.path) AS file_path, n.start_line AS start_line "
                "ORDER BY file_path, n.start_line",
                {"cid": page_id},
                what="feature members",
            )
        ]

    repo_info = next((r for r in scope.repos if r.name == props.get("repo")), None)
    repo_root_accessible = bool(repo_info and repo_info.root and Path(repo_info.root).is_dir())

    return {
        "page": props, "members": members, "mentions": mentions,
        "indexing_job": indexing_job, "repo_root_accessible": repo_root_accessible,
    }


@router.put("/{app}/docs/{page_id}")
def update_doc(
    app: str,
    page_id: str,
    body: FeatureDocUpdate,
    registry: ApplicationRegistry = Depends(get_registry),
    graph=Depends(get_graph),
    vector_store=Depends(get_vector_store),
    embedder=Depends(get_embedder),
    jobs=Depends(get_docs_jobs),
):
    scope = _scope_or_404(registry, app)
    props = _fetch_page(graph, app, page_id, types=("Feature", "Document"))
    if not props:
        raise HTTPException(status_code=404, detail=f"Page '{page_id}' not found")
    if body.expected_edited_at is not None and (props.get("edited_at") or None) != body.expected_edited_at:
        raise HTTPException(status_code=409, detail="This page changed since you loaded it. Reload and retry.")

    page_type = props.get("type")
    if page_type not in ("Feature", "Document"):
        raise HTTPException(status_code=400, detail="Only Feature and Document pages are editable")

    if page_type == "Document":
        doc_id = props.get("concept_id") or page_id
        if jobs.is_running(app, "index_document", key=doc_id):
            raise HTTPException(status_code=409, detail="This document is already being indexed.")

        title = extract_title(body.markdown)
        result = validate_document_body(body.markdown, title=title)
        if not result.ok:
            raise HTTPException(status_code=422, detail={"validation": _result_to_dict(result)})

        now = datetime.now(timezone.utc).isoformat()
        saved = save_document_page(
            graph, doc_id, content=body.markdown, title=title, description=first_paragraph(body.markdown),
            tags=body.tags if body.tags is not None else list(props.get("tags") or []),
            category=body.category or props.get("category") or "note", now=now, needs_reembed=True,
            word_count=word_count(body.markdown), source_file=None,
        )
        if saved is None:
            raise HTTPException(status_code=404, detail=f"Page '{page_id}' not found")

        page = document_page_from_props(saved)

        def _run(report) -> dict[str, Any]:
            report("linking_mentions")
            mentions = resolve_mentions(graph, scope, extract_mentioned_paths(page.body))
            set_mentions(graph, doc_id, mentions)
            chunks, needs_reembed = _index_document_vectors(page, report, vector_store, embedder, graph)
            report("writing_bundle")
            write_document_bundle_file(page, CVG_DOCS_BUNDLE_DIR)
            return {"chunks": chunks, "mentions": len(mentions), "needs_reembed": needs_reembed}

        job_id = jobs.start(
            app, saved.get("repo"), _run, kind="index_document", key=doc_id, stages=_DOCUMENT_INDEX_STAGES,
            target={"doc_id": doc_id, "slug": saved.get("slug"), "title": title},
        )
        return {"page": saved, "validation": _result_to_dict(result), "reembedded": False, "job_id": job_id}

    # ---- Feature branch ----
    title = extract_title(body.markdown) or props.get("title") or "Untitled"
    result = validate_feature_body(body.markdown, title=title)
    if not result.ok:
        raise HTTPException(status_code=422, detail={"validation": _result_to_dict(result)})

    overview = parse_sections(body.markdown).get("Overview", "")
    needs_reembed = vector_store is not None and embedder is None
    now = datetime.now(timezone.utc).isoformat()

    saved = save_feature_page(
        graph, page_id, content=body.markdown, title=title, summary=props.get("summary") or "",
        overview=overview, tags=body.tags if body.tags is not None else list(props.get("tags") or []),
        source=body.source, now=now, needs_reembed=needs_reembed,
    )
    if saved is None:
        raise HTTPException(status_code=404, detail=f"Feature '{page_id}' not found")

    reembedded = False
    if vector_store is not None and embedder is not None:
        fm = _frontmatter_from_props(saved)
        stats = sync_features_qdrant(
            [FeaturePage(fm=fm, body=body.markdown)], embedder, vector_store, MODEL_CONFIGS[MODEL_ID]["tokenizer_name"]
        )
        reembedded = stats.get("chunks", 0) > 0

    bundle_written = _maybe_write_bundle_file(saved)
    return {"page": saved, "validation": _result_to_dict(result), "reembedded": reembedded, "bundle_written": bundle_written}


@router.post("/{app}/docs/{page_id}/reindex", status_code=202)
def reindex_doc(
    app: str,
    page_id: str,
    registry: ApplicationRegistry = Depends(get_registry),
    graph=Depends(get_graph),
    vector_store=Depends(get_vector_store),
    embedder=Depends(get_embedder),
    jobs=Depends(get_docs_jobs),
):
    scope = _scope_or_404(registry, app)
    props = _fetch_page(graph, app, page_id, types=("Feature", "Document"))
    if not props:
        raise HTTPException(status_code=404, detail=f"Page '{page_id}' not found")

    page_type = props.get("type")
    page_key = props.get("concept_id") or page_id
    if jobs.is_running(app, "index_document", key=page_key):
        raise HTTPException(status_code=409, detail="This page is already being indexed.")

    if page_type == "Document":
        page = document_page_from_props(props)

        def _run(report) -> dict[str, Any]:
            report("linking_mentions")
            mentions = resolve_mentions(graph, scope, extract_mentioned_paths(page.body))
            set_mentions(graph, page_key, mentions)
            chunks, needs_reembed = _index_document_vectors(page, report, vector_store, embedder, graph)
            report("writing_bundle")
            write_document_bundle_file(page, CVG_DOCS_BUNDLE_DIR)
            return {"chunks": chunks, "mentions": len(mentions), "needs_reembed": needs_reembed}

        job_id = jobs.start(
            app, props.get("repo"), _run, kind="index_document", key=page_key, stages=_DOCUMENT_INDEX_STAGES,
            target={"doc_id": page_key, "slug": props.get("slug"), "title": props.get("title")},
        )
        return {"job_id": job_id, "status": "queued"}

    if page_type != "Feature":
        raise HTTPException(status_code=400, detail="Only Feature and Document pages can be reindexed")

    fm = _frontmatter_from_props(props)
    feature_page = FeaturePage(fm=fm, body=props.get("content") or "")
    tokenizer_name = MODEL_CONFIGS[MODEL_ID]["tokenizer_name"]

    def _run_feature(report) -> dict[str, Any]:
        report("embedding")
        if vector_store is not None and embedder is not None:
            stats = sync_features_qdrant([feature_page], embedder, vector_store, tokenizer_name)
            graph.query_graph(
                "MATCH (w:WikiPage {type:'Feature'}) WHERE w.concept_id = $cid OR w.id = $cid SET w.needs_reembed = false",
                {"cid": page_key},
            )
            chunks, needs_reembed = stats.get("chunks", 0), False
        else:
            chunks, needs_reembed = 0, True
        report("upserting_vectors")
        return {"chunks": chunks, "needs_reembed": needs_reembed}

    job_id = jobs.start(
        app, props.get("repo"), _run_feature, kind="index_document", key=page_key,
        stages=("embedding", "upserting_vectors", "done"),
        target={"doc_id": page_key, "slug": props.get("slug"), "title": props.get("title")},
    )
    return {"job_id": job_id, "status": "queued"}


@router.delete("/{app}/docs/{page_id}")
def delete_doc(
    app: str,
    page_id: str,
    registry: ApplicationRegistry = Depends(get_registry),
    graph=Depends(get_graph),
    vector_store=Depends(get_vector_store),
    jobs=Depends(get_docs_jobs),
):
    _scope_or_404(registry, app)
    props = _fetch_page(graph, app, page_id, types=("Feature", "Document"))
    if not props:
        raise HTTPException(status_code=404, detail=f"Page '{page_id}' not found")
    if props.get("type") != "Document":
        raise HTTPException(
            status_code=400,
            detail="Only Document pages can be deleted directly; Feature pages are managed by 'Generate docs'.",
        )

    doc_id = props.get("concept_id") or page_id
    if jobs.is_running(app, "index_document", key=doc_id):
        raise HTTPException(status_code=409, detail="This document is currently being indexed.")

    delete_document(graph, vector_store, wiki_id(doc_id), doc_id)
    remove_document_bundle_file(props.get("slug") or "", CVG_DOCS_BUNDLE_DIR)
    return {"deleted": True}


@router.post("/{app}/docs/{feature_id}/regenerate")
def regenerate_doc(
    app: str,
    feature_id: str,
    save_draft: bool = Query(default=False),
    registry: ApplicationRegistry = Depends(get_registry),
    graph=Depends(get_graph),
    llm_client=Depends(get_llm_client),
):
    scope = _scope_or_404(registry, app)
    props = _fetch_page(graph, app, feature_id)
    if not props:
        raise HTTPException(status_code=404, detail=f"Feature '{feature_id}' not found")
    if llm_client is None:
        raise HTTPException(
            status_code=503,
            detail="No enrichment LLM is configured on the server (set DEEPSEEK_API_KEY, "
                   "or OKF_LLM_PROVIDER=omlx with a running oMLX server)",
        )

    spec = FeatureSpec(
        slug=props.get("slug") or "feature", title=props.get("title") or "Untitled",
        description=props.get("summary") or "", kind=props.get("kind") or "other",
        member_files=list(props.get("member_files") or []), tags=list(props.get("tags") or []),
    )
    language = props.get("language") or CVG_DOCS_LANGUAGE
    repo_info = next((r for r in scope.repos if r.name == props.get("repo")), None)

    if repo_info and repo_info.root and Path(repo_info.root).is_dir():
        skeleton = build_skeleton(repo_info.root)
        inventory = build_inventory(skeleton, {})
        grounding = "source"
    else:
        skeleton = _EMPTY_SKELETON
        inventory = _graph_only_inventory(spec.member_files)
        grounding = "graph-only"

    body_md, _used_fallback, _warnings = generate_feature_doc(
        llm_client, OKF_FEATURES_MODEL, spec, skeleton, inventory, language=language
    )
    result = validate_feature_body(body_md, title=spec.title)
    now = datetime.now(timezone.utc).isoformat()

    if save_draft:
        graph.query_graph(
            "MATCH (w:WikiPage {type:'Feature'}) WHERE (w.concept_id = $cid OR w.id = $cid) AND w.app = $app "
            "SET w.draft = $draft, w.draft_generated_at = $now",
            {"cid": feature_id, "app": app, "draft": body_md, "now": now},
        )

    return {
        "draft": body_md, "model": OKF_FEATURES_MODEL, "generated_at": now,
        "grounding": grounding, "validation": _result_to_dict(result),
    }
