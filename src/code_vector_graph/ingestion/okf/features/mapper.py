"""Stage 1 of feature-doc generation: group a repo's files into a `FeatureMap`.

One or more LLM "map" calls (one per `chunk_inventory` group) propose
candidate features; if there was more than one chunk, a "merge" call
deduplicates candidates that represent the same feature split across chunks.
A deterministic post-pass then guarantees every file is covered by exactly
one feature, reuses prior-run slugs so ids stay stable across reindexes, and
enforces the per-feature and total-feature caps.
"""

from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from typing import Any

from code_vector_graph.ingestion.okf.enricher import _call_llm
from code_vector_graph.ingestion.okf.features.inventory import chunk_inventory
from code_vector_graph.ingestion.okf.features.models import FeatureMap, FeatureSpec, FileInventory
from code_vector_graph.ingestion.okf.skeleton import slugify

logger = logging.getLogger(__name__)

INFRA_SLUG = "other-infrastructure"
INFRA_TITLE = "Other / Infrastructure"
INFRA_DESCRIPTION = "Shared/technical files not attributed to a specific business feature."

_MAP_RETRIES = 2
# DeepSeek V4 caps output at 8192 tokens; thinking is disabled for these calls
# (see enricher._call_llm) so the whole budget goes to the JSON answer. For a
# small local model (oMLX) lower OKF_FEATURE_MAP_MAX_CHARS if the prompt plus
# this budget exceeds the model's context window.
_MAP_MAX_TOKENS = 8000
_MERGE_MAX_TOKENS = 8000
_MAX_MEMBERS_PER_FEATURE = 80
_SLUG_REUSE_THRESHOLD = 0.6
_VALID_KINDS = {"user-facing", "integration", "data", "infrastructure", "other"}

_MAP_SYSTEM_PROMPT = (
    "You are a senior engineer grouping a codebase's files into business FEATURES "
    "for internal documentation. A feature is a cohesive piece of business "
    "functionality (e.g. 'User Authentication', 'Order Checkout', 'Tender Deadline "
    "Reminders') implemented by a cluster of files — not a single file, and not a "
    "purely technical layer ('utils', 'config') unless that IS the feature. Group by "
    "what the code DOES for the business; directory hints are useful but not "
    "authoritative. Respond with a single JSON object and nothing else:\n"
    "{\n"
    '  "features": [\n'
    '    {"slug": "kebab-case-slug", "title": "Human Title", "description": "one sentence",\n'
    '     "kind": "user-facing|integration|data|infrastructure|other",\n'
    '     "member_files": ["path exactly as given"], "entry_points_hint": ["GET /x"], "tags": ["tag"]}\n'
    "  ]\n"
    "}\n"
    "Rules: every file you were given must appear in exactly one feature's "
    "member_files (use only the paths given — never invent one). Files with no clear "
    "business feature belong together in one group with kind \"infrastructure\". If "
    "PRIOR FEATURES are given, reuse a prior slug/title whenever it still matches the "
    "same feature — do not invent a new slug for something that already exists. "
    "Output JSON only."
)

_MERGE_SYSTEM_PROMPT = (
    "You are merging partial feature maps into one deduplicated map covering an "
    "entire repository. The candidates were proposed independently for different "
    "parts of the codebase, so the same real feature may appear more than once "
    "under different names (e.g. its frontend and backend files were mapped "
    "separately) — merge those into a single entry. Respond with a single JSON "
    "object in the same shape as the input candidates, plus an optional "
    '"merged_from" list of the slugs that were combined:\n'
    "{\"features\": [{\"slug\", \"title\", \"description\", \"kind\", \"member_files\", "
    '"entry_points_hint", "tags", "merged_from": ["slug1", "slug2"]}]}\n'
    "Preserve every member_files entry from every input candidate — do not drop "
    "files while merging. Output JSON only."
)


def _inventory_line(f: FileInventory) -> str:
    bits = [f"- {f.rel_path} ({f.language or 'unknown'})"]
    if f.exports:
        bits.append("exports: " + ", ".join(f.exports[:12]))
    if f.symbols:
        bits.append("symbols: " + "; ".join(f.symbols[:12]))
    if f.routes:
        bits.append("routes: " + ", ".join(f.routes[:8]))
    if f.summary:
        bits.append("summary: " + f.summary[:200])
    return " | ".join(bits)


def _prior_block(prior: FeatureMap | None, paths: set[str]) -> str:
    if not prior or not prior.features:
        return ""
    relevant = [f for f in prior.features if set(f.member_files) & paths]
    if not relevant:
        return ""
    lines = ["PRIOR FEATURES (reuse these slugs/titles when the same feature still exists):"]
    for f in relevant:
        lines.append(f"- slug={f.slug} title=\"{f.title}\" member_files={f.member_files[:20]}")
    return "\n".join(lines)


def _merge_duplicate_slugs(specs: list[FeatureSpec]) -> list[FeatureSpec]:
    by_slug: dict[str, FeatureSpec] = {}
    for s in specs:
        if s.slug in by_slug:
            existing = by_slug[s.slug]
            existing.member_files = sorted(set(existing.member_files) | set(s.member_files))
            existing.tags = sorted(set(existing.tags) | set(s.tags))
        else:
            by_slug[s.slug] = s.model_copy(deep=True)
    return list(by_slug.values())


def _coerce_feature_specs(raw: Any, allowed_paths: set[str] | None = None) -> list[FeatureSpec]:
    if not isinstance(raw, dict) or not isinstance(raw.get("features"), list):
        return []
    out: list[FeatureSpec] = []
    for item in raw["features"]:
        if not isinstance(item, dict):
            continue
        title = str(item.get("title") or "").strip()
        if not title:
            continue
        slug = slugify(str(item.get("slug") or title))
        if not slug:
            continue
        member_files = [p for p in (item.get("member_files") or []) if isinstance(p, str)]
        if allowed_paths is not None:
            member_files = [p for p in member_files if p in allowed_paths]
        if not member_files:
            continue
        kind = item.get("kind") if item.get("kind") in _VALID_KINDS else "other"
        out.append(
            FeatureSpec(
                slug=slug,
                title=title,
                description=str(item.get("description") or "").strip(),
                kind=kind,
                member_files=sorted(set(member_files)),
                entry_points_hint=[str(x) for x in (item.get("entry_points_hint") or []) if isinstance(x, str)],
                tags=[str(x) for x in (item.get("tags") or []) if isinstance(x, str)],
            )
        )
    return _merge_duplicate_slugs(out)


def _call_map(
    client,
    model: str,
    chunk: list[FileInventory],
    prior: FeatureMap | None,
    warnings: list[str] | None = None,
) -> list[FeatureSpec]:
    """LLM feature map for one inventory chunk. On repeated failure returns the
    per-directory `structural_fallback` and, if `warnings` is given, records
    why — so a build that silently degraded to folder-named "features" is
    visible in the job result rather than only in server logs."""
    paths = {f.rel_path for f in chunk}
    user = "Files to group into features:\n" + "\n".join(_inventory_line(f) for f in chunk)
    prior_block = _prior_block(prior, paths)
    if prior_block:
        user += "\n\n" + prior_block
    user += "\n\nGroup ALL of the above files into features now."

    last_exc: Exception | None = None
    for attempt in range(_MAP_RETRIES + 1):
        try:
            raw = _call_llm(client, model, _MAP_SYSTEM_PROMPT, user, max_tokens=_MAP_MAX_TOKENS)
            specs = _coerce_feature_specs(raw, allowed_paths=paths)
            if specs:
                return specs
        except Exception as exc:  # network/rate-limit/parse errors — retried, then falls back
            last_exc = exc
            time.sleep(min(2**attempt, 4))
    msg = (
        f"Feature-map LLM call ({model}) failed for a {len(chunk)}-file chunk after {_MAP_RETRIES + 1} attempts "
        f"({last_exc}); grouped those files by top-level directory instead (kind='other')."
    )
    logger.warning(msg)
    if warnings is not None:
        warnings.append(msg)
    return structural_fallback(chunk)


def _call_merge(client, model: str, candidates: list[FeatureSpec], allowed_paths: set[str]) -> list[FeatureSpec]:
    import json

    payload = {"features": [c.model_dump() for c in candidates]}
    user = f"Candidate feature groups from different parts of the repo:\n{json.dumps(payload, ensure_ascii=False)}\n\nMerge them now."
    try:
        raw = _call_llm(client, model, _MERGE_SYSTEM_PROMPT, user, max_tokens=_MERGE_MAX_TOKENS)
        merged = _coerce_feature_specs(raw, allowed_paths=allowed_paths)
        if merged:
            return merged
    except Exception as exc:
        logger.warning("Feature-map merge call failed (%s); keeping per-chunk candidates unmerged.", exc)
    return _merge_duplicate_slugs(candidates)


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    union = len(a | b)
    return len(a & b) / union if union else 0.0


def _reuse_prior_slugs(specs: list[FeatureSpec], prior: FeatureMap | None) -> list[FeatureSpec]:
    if not prior or not prior.features:
        return specs
    used_prior: set[str] = set()
    out: list[FeatureSpec] = []
    for spec in specs:
        members = set(spec.member_files)
        best, best_score = None, 0.0
        for pf in prior.features:
            if pf.slug in used_prior:
                continue
            score = _jaccard(members, set(pf.member_files))
            if score > best_score:
                best, best_score = pf, score
        if best is not None and best_score >= _SLUG_REUSE_THRESHOLD and best.slug != spec.slug:
            used_prior.add(best.slug)
            spec = spec.model_copy(update={"slug": best.slug, "title": best.title})
        out.append(spec)
    return out


def _ensure_coverage(specs: list[FeatureSpec], all_paths: set[str]) -> list[FeatureSpec]:
    covered = {p for s in specs for p in s.member_files}
    missing = sorted(all_paths - covered)
    if not missing:
        return specs
    for s in specs:
        if s.slug == INFRA_SLUG:
            s.member_files = sorted(set(s.member_files) | set(missing))
            return specs
    return list(specs) + [
        FeatureSpec(
            slug=INFRA_SLUG, title=INFRA_TITLE, description=INFRA_DESCRIPTION,
            kind="infrastructure", member_files=missing,
        )
    ]


def _cap_members(specs: list[FeatureSpec], max_members: int) -> tuple[list[FeatureSpec], list[str]]:
    warnings: list[str] = []
    overflow: list[str] = []
    capped: list[FeatureSpec] = []
    for s in specs:
        if len(s.member_files) > max_members:
            warnings.append(
                f"Feature '{s.slug}' had {len(s.member_files)} members; capped at {max_members}, "
                f"overflow moved to '{INFRA_SLUG}'."
            )
            overflow.extend(s.member_files[max_members:])
            s = s.model_copy(update={"member_files": s.member_files[:max_members]})
        capped.append(s)
    if overflow:
        infra = next((s for s in capped if s.slug == INFRA_SLUG), None)
        if infra is not None:
            infra.member_files = sorted(set(infra.member_files) | set(overflow))
        else:
            capped.append(
                FeatureSpec(
                    slug=INFRA_SLUG, title=INFRA_TITLE, description=INFRA_DESCRIPTION,
                    kind="infrastructure", member_files=sorted(set(overflow)),
                )
            )
    return capped, warnings


def _cap_total_features(specs: list[FeatureSpec], max_features: int) -> list[FeatureSpec]:
    if max_features <= 0 or len(specs) <= max_features:
        return specs
    infra = next((s for s in specs if s.slug == INFRA_SLUG), None)
    others = sorted((s for s in specs if s.slug != INFRA_SLUG), key=lambda s: len(s.member_files), reverse=True)
    kept = others[: max_features - 1]
    overflow_paths = [p for s in others[max_features - 1 :] for p in s.member_files]
    if infra is None:
        infra = FeatureSpec(slug=INFRA_SLUG, title=INFRA_TITLE, description=INFRA_DESCRIPTION, kind="infrastructure")
    infra.member_files = sorted(set(infra.member_files) | set(overflow_paths))
    return kept + [infra]


def structural_fallback(inventory: list[FileInventory]) -> list[FeatureSpec]:
    """One feature per top-level directory — used for `--dry-run` and when an
    LLM map call fails for a chunk."""
    by_dir: dict[str, list[str]] = {}
    for f in inventory:
        by_dir.setdefault(f.top_dir, []).append(f.rel_path)
    specs = []
    for top_dir in sorted(by_dir):
        title = "Root" if top_dir == "." else top_dir.replace("_", " ").replace("-", " ").title()
        specs.append(
            FeatureSpec(
                slug=slugify(top_dir) or "root", title=title, description="",
                kind="other", member_files=sorted(by_dir[top_dir]),
            )
        )
    return specs


def discover_features(
    client,
    model: str,
    inventory: list[FileInventory],
    *,
    app: str,
    repo: str,
    prior: FeatureMap | None = None,
    max_files: int = 250,
    max_chars: int = 60_000,
    max_features: int = 40,
    max_members_per_feature: int = _MAX_MEMBERS_PER_FEATURE,
    dry_run: bool = False,
) -> tuple[FeatureMap, list[str]]:
    """Two-stage LLM feature discovery, followed by a deterministic pass that
    guarantees full file coverage and enforces the size caps. Returns the
    `FeatureMap` and any warnings worth surfacing to the caller."""
    warnings: list[str] = []
    all_paths = {f.rel_path for f in inventory}

    if dry_run or client is None:
        specs = structural_fallback(inventory)
        effective_model = "structural"
    else:
        chunks = chunk_inventory(inventory, max_files=max_files, max_chars=max_chars)
        per_chunk: list[FeatureSpec] = []
        for chunk in chunks:
            per_chunk.extend(_call_map(client, model, chunk, prior, warnings))
        specs = _call_merge(client, model, per_chunk, all_paths) if len(chunks) > 1 else _merge_duplicate_slugs(per_chunk)
        effective_model = model

    specs = _reuse_prior_slugs(specs, prior)
    specs = _ensure_coverage(specs, all_paths)
    specs, cap_warnings = _cap_members(specs, max_members_per_feature)
    warnings.extend(cap_warnings)
    specs = _cap_total_features(specs, max_features)
    specs.sort(key=lambda s: s.title.lower())

    feature_map = FeatureMap(
        app=app, repo=repo, generated_at=datetime.now(timezone.utc).isoformat(), model=effective_model, features=specs
    )
    return feature_map, warnings
