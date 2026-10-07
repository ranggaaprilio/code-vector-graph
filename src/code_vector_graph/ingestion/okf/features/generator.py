"""Stage 2 of feature-doc generation: write one validated page per feature.

Context is the feature's member files (summaries/exports/symbols from the
inventory) plus bounded source excerpts — exported/entry-point symbols first,
then the largest remaining ones — capped by a character budget. The LLM's
JSON is rendered to Markdown and structurally validated; a validation
failure is retried once with the errors appended to the prompt, and a second
failure falls back to a purely structural page so a build never blocks on
one bad feature.
"""

from __future__ import annotations

import logging
import time

from code_vector_graph.ingestion.okf.enricher import _call_llm, _read_source_slice
from code_vector_graph.ingestion.okf.features.models import Entity, EntryPoint, FeatureDoc, FeatureSpec, FileInventory
from code_vector_graph.ingestion.okf.features.template import render_feature_markdown
from code_vector_graph.ingestion.okf.features.validate import validate_feature_body
from code_vector_graph.ingestion.okf.skeleton import Skeleton, concept_name

logger = logging.getLogger(__name__)

DEFAULT_SOURCE_BUDGET = 24_000
_PER_SYMBOL_CHARS = 4_000
_MAX_TOKENS = 4000
_RETRIES = 2

SYSTEM_PROMPT_TEMPLATE = (
    "You are a senior engineer writing internal product documentation for one BUSINESS "
    "FEATURE of a codebase, for other engineers who need to understand WHY the code "
    "behaves the way it does, not just what each function does. Focus on business rules, "
    "invariants, validations, state transitions, actors, and decisions — not a "
    "function-by-function walkthrough. Be concrete and grounded in the provided code and "
    "file summaries; never invent behavior, rules, or integrations that aren't evidenced. "
    "Write in {language}.\n\n"
    "Respond with a single JSON object and nothing else, in exactly this shape:\n"
    "{{\n"
    '  "title": "Human Feature Title",\n'
    '  "description": "<=300 chars, one sentence",\n'
    '  "overview": "1-2 paragraphs: what this feature does for the business and who uses it",\n'
    '  "business_rules": ["imperative sentence, grounded in code"],\n'
    '  "process_flow": ["step 1", "step 2", "..."],\n'
    '  "entities": [{{"name": "EntityName", "description": "fields/role used by this feature"}}],\n'
    '  "entry_points": [{{"kind": "HTTP|Cron|Queue|CLI|...", "name": "handlerName", "file": "path", "line": 12}}],\n'
    '  "dependencies": ["InternalService or external API name"],\n'
    '  "edge_cases": ["edge case and how it is handled"],\n'
    '  "open_questions": ["anything unclear from the code alone"],\n'
    '  "tags": ["short-topic-tag"],\n'
    '  "mermaid": "optional flowchart TD ... (omit or null if not useful)"\n'
    "}}\n"
    "Rules: 'process_flow' must have at least 2 steps. 'business_rules' must have at least "
    "one entry — if the code truly has none, state that explicitly as a rule. Output JSON only."
)


def _member_inventory(spec: FeatureSpec, inventory: list[FileInventory]) -> list[FileInventory]:
    by_path = {f.rel_path: f for f in inventory}
    return [by_path[p] for p in spec.member_files if p in by_path]


def _context_block(spec: FeatureSpec, members: list[FileInventory]) -> str:
    lines = [f"Feature candidate: {spec.title}", f"Kind: {spec.kind}"]
    if spec.description:
        lines.append(f"Working description: {spec.description}")
    lines.append("Member files:")
    for m in members:
        bits = [f"- {m.rel_path}"]
        if m.summary:
            bits.append(f"summary: {m.summary}")
        if m.exports:
            bits.append("exports: " + ", ".join(m.exports[:10]))
        if m.symbols:
            bits.append("symbols: " + "; ".join(m.symbols[:10]))
        if m.routes:
            bits.append("routes: " + ", ".join(m.routes[:6]))
        lines.append(" | ".join(bits))
    return "\n".join(lines)


def _size_hint(node: dict) -> int:
    props = node.get("properties", {}) or {}
    if node.get("label") == "File":
        return int(props.get("line_count") or 0)
    try:
        return int(props.get("end_line", 0)) - int(props.get("start_line", 0))
    except (TypeError, ValueError):
        return 0


def _source_excerpts(skeleton: Skeleton, members: list[FileInventory], budget: int) -> str:
    """Bounded source: exported/entry-point symbols first, then by size."""
    candidates: list[tuple[int, int, dict, str]] = []  # (priority, -size, node, rel_path)
    for m in members:
        file_node = skeleton.nodes.get(m.file_id)
        if file_node is None:
            continue
        children = skeleton.contains.get(m.file_id, [])
        if not children:
            candidates.append((0 if m.routes else 1, -_size_hint(file_node), file_node, m.rel_path))
            continue
        for cid in children:
            child = skeleton.nodes.get(cid)
            if not child:
                continue
            cprops = child.get("properties", {}) or {}
            priority = 0 if (cprops.get("is_exported") or cprops.get("decorators")) else 1
            candidates.append((priority, -_size_hint(child), child, m.rel_path))
    candidates.sort(key=lambda c: (c[0], c[1]))

    parts: list[str] = []
    spent = 0
    for _, _, node, rel_path in candidates:
        if spent >= budget:
            break
        text = _read_source_slice(node, max_chars=min(_PER_SYMBOL_CHARS, budget - spent))
        if not text:
            continue
        parts.append(f"--- {rel_path} :: {concept_name(node)} ({node.get('label')}) ---\n{text}")
        spent += len(text)
    return "\n\n".join(parts)


def _coerce_feature_doc(raw: dict, spec: FeatureSpec) -> FeatureDoc:
    def _str_list(key: str) -> list[str]:
        return [str(x).strip() for x in (raw.get(key) or []) if isinstance(x, (str, int, float)) and str(x).strip()]

    entities = [
        Entity(name=str(e["name"]).strip(), description=str(e.get("description") or "").strip())
        for e in (raw.get("entities") or [])
        if isinstance(e, dict) and e.get("name")
    ]
    entry_points = []
    for ep in raw.get("entry_points") or []:
        if isinstance(ep, dict) and ep.get("name"):
            line = ep.get("line")
            entry_points.append(
                EntryPoint(
                    kind=str(ep.get("kind") or "-").strip(),
                    name=str(ep["name"]).strip(),
                    file=str(ep.get("file") or "").strip(),
                    line=int(line) if isinstance(line, (int, float)) else None,
                )
            )
    mermaid = raw.get("mermaid")
    mermaid = str(mermaid).strip() if isinstance(mermaid, str) and mermaid.strip() else None

    return FeatureDoc(
        title=str(raw.get("title") or spec.title).strip() or spec.title,
        description=str(raw.get("description") or spec.description or "").strip()[:300],
        overview=str(raw.get("overview") or "").strip(),
        business_rules=_str_list("business_rules"),
        process_flow=_str_list("process_flow"),
        entities=entities,
        entry_points=entry_points,
        dependencies=_str_list("dependencies"),
        edge_cases=_str_list("edge_cases"),
        open_questions=_str_list("open_questions"),
        tags=_str_list("tags") or list(spec.tags),
        mermaid=mermaid,
    )


def fallback_feature_doc(spec: FeatureSpec, members: list[FileInventory]) -> FeatureDoc:
    """Structural doc used when no LLM client is given, or generation fails
    validation after retries."""
    file_list = ", ".join(m.rel_path for m in members[:10])
    overview = spec.description.strip() or (
        f"This feature groups the following files: {file_list}." if file_list else spec.title
    )
    dependencies = sorted({e for m in members for e in m.exports})[:15]
    return FeatureDoc(
        title=spec.title,
        description=spec.description,
        overview=overview,
        dependencies=dependencies,
        tags=list(spec.tags),
        open_questions=[
            "This page was generated structurally (LLM enrichment was unavailable or failed); "
            "verify the business rules manually."
        ],
    )


def generate_feature_doc(
    client,
    model: str,
    spec: FeatureSpec,
    skeleton: Skeleton,
    inventory: list[FileInventory],
    language: str = "en",
    source_budget: int = DEFAULT_SOURCE_BUDGET,
) -> tuple[str, bool, list[str]]:
    """Generate and validate one feature's Markdown body.

    Returns ``(body, used_fallback, warnings)``. ``body`` always passes
    `validate_feature_body` — the structural fallback is built from
    `render_feature_markdown`, which itself guarantees every required
    section is non-empty.
    """
    members = _member_inventory(spec, inventory)
    warnings: list[str] = []

    if client is None:
        doc = fallback_feature_doc(spec, members)
        return render_feature_markdown(spec.title, doc), True, warnings

    system = SYSTEM_PROMPT_TEMPLATE.format(language=language or "en")
    context = _context_block(spec, members)
    source = _source_excerpts(skeleton, members, source_budget)
    user = f"{context}\n\nSource excerpts:\n```\n{source}\n```\n\nWrite the JSON feature doc now."

    last_errors: list[str] = []
    for attempt in range(_RETRIES + 1):
        if last_errors:
            user += "\n\nYour previous reply had these problems — fix them:\n" + "\n".join(
                f"- {e}" for e in last_errors
            )
        try:
            raw = _call_llm(client, model, system, user, max_tokens=_MAX_TOKENS)
        except Exception as exc:  # network/rate-limit/parse errors
            warnings.append(f"Feature-doc call failed for '{spec.slug}' (attempt {attempt + 1}): {exc}")
            time.sleep(min(2**attempt, 4))
            continue
        doc = _coerce_feature_doc(raw if isinstance(raw, dict) else {}, spec)
        body = render_feature_markdown(doc.title or spec.title, doc)
        result = validate_feature_body(body, title=doc.title or spec.title)
        if result.ok:
            return body, False, warnings
        last_errors = [f"{e.code}: {e.message}" for e in result.errors]

    warnings.append(f"Feature-doc generation for '{spec.slug}' failed validation after retries; using a structural fallback.")
    doc = fallback_feature_doc(spec, members)
    return render_feature_markdown(spec.title, doc), True, warnings
