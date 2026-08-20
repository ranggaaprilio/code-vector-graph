"""DeepSeek enrichment agent — writes plain-language wiki content per concept.

The agent walks the skeleton bottom-up (leaf functions/methods -> classes ->
files), reads each concept's source plus its grounded neighbors, and asks
DeepSeek for a structured JSON page (summary, overview, how-it-works, params,
tags, related). Higher-level concepts receive their children's one-line
summaries so their pages stay coherent (the DeepWiki pattern).

DeepSeek is OpenAI-compatible, so the `openai` SDK (already a dependency) is
pointed at the DeepSeek base URL. Structured output uses JSON mode
(`response_format={"type": "json_object"}`) with the schema described in the
system prompt, validated/repaired in Python.
"""

from __future__ import annotations

import json
import logging
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Callable, Optional

from src.okf import cache as okf_cache
from src.okf.skeleton import Skeleton, concept_name

logger = logging.getLogger(__name__)

OVERVIEW_KEY = "__overview__"
MAX_SOURCE_CHARS = 8000
MAX_CALLS = 30
MAX_CHILDREN_CONTEXT = 40
_MAX_TOKENS = 1500
_RETRIES = 3

# Bottom-up processing levels: enrich level 0 before 1 before 2 so parents can
# quote their children's summaries.
_LEVEL = {
    "Function": 0, "Method": 0, "Field": 0, "Variable": 0, "TypeAlias": 0, "Import": 0,
    "Interface": 1, "Class": 1,
    "File": 2,
}

SYSTEM_PROMPT = (
    "You are a senior engineer writing an internal developer wiki for a codebase. "
    "For each code concept (a file, class, function, method, interface, or type) you are "
    "given its source and its relationships to other concepts. Write a clear, accurate, "
    "human-readable wiki entry that explains WHAT it is, WHAT it does, and HOW it fits into "
    "the system. Be concrete and grounded in the provided code — never invent behavior, "
    "parameters, or relationships that are not evidenced. Prefer plain language over jargon.\n\n"
    "Respond with a single JSON object and nothing else, in exactly this shape:\n"
    "{\n"
    '  "summary": "one sentence, <= 160 chars, what this is/does",\n'
    '  "overview": "1-2 short paragraphs in plain language",\n'
    '  "how_it_works": "markdown explanation of behavior/flow; bullet points allowed; may be empty for trivial items",\n'
    '  "parameters": [{"name": "arg", "description": "what it is"}],\n'
    '  "tags": ["short-topic-tag"],\n'
    '  "related": ["OtherConceptName"]\n'
    "}\n"
    "Rules: 'parameters' only for functions/methods (else []). 'related' must be names that "
    "appear in the provided relationships/neighbors (else []). Keep it concise. Output JSON only."
)


def make_client(api_key: str, base_url: str):
    """Construct an OpenAI-SDK client pointed at DeepSeek."""
    from openai import OpenAI  # imported lazily so tests can run without the dep loaded

    if not api_key:
        raise ValueError(
            "DEEPSEEK_API_KEY is not set. Add it to your environment or .env "
            "(see .env.example)."
        )
    return OpenAI(api_key=api_key, base_url=base_url)


def _read_source_slice(node: dict, max_chars: int = MAX_SOURCE_CHARS) -> str:
    """Read a concept's source lines from disk (best-effort), truncated."""
    fmeta = node.get("_file", {}) or {}
    path = fmeta.get("path") or (node.get("properties", {}) or {}).get("path")
    if not path or not Path(path).exists():
        return ""
    props = node.get("properties", {}) or {}
    try:
        lines = Path(path).read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return ""
    if node.get("label") == "File":
        text = "\n".join(lines)
    else:
        start = max(1, int(props.get("start_line", 1))) - 1
        end = int(props.get("end_line", len(lines)))
        text = "\n".join(lines[start:end])
    if len(text) > max_chars:
        text = text[:max_chars] + "\n… (truncated)"
    return text


def _build_context(skeleton: Skeleton, node: dict, enrichments: dict[str, dict]) -> str:
    """Grounded neighbor context: signature, calls, imports, children summaries."""
    props = node.get("properties", {}) or {}
    label = node.get("label", "")
    lines: list[str] = [f"Concept type: {label}", f"Name: {concept_name(node)}"]

    fmeta = node.get("_file", {}) or {}
    if fmeta.get("path"):
        lines.append(f"File: {fmeta['path']}")
    if props.get("start_line") and props.get("end_line"):
        lines.append(f"Lines: {props['start_line']}-{props['end_line']}")

    sig = []
    if props.get("parameters"):
        sig.append(f"parameters: {', '.join(props['parameters'])}")
    if props.get("is_async"):
        sig.append("async")
    if props.get("visibility"):
        sig.append(f"visibility: {props['visibility']}")
    if props.get("decorators"):
        sig.append(f"decorators: {', '.join(props['decorators'])}")
    if props.get("parent_class"):
        sig.append(f"parent class: {props['parent_class']}")
    if props.get("extends"):
        sig.append(f"extends: {', '.join(props['extends'])}")
    if props.get("type_expression"):
        sig.append(f"type: {props['type_expression']}")
    if sig:
        lines.append("Signature: " + "; ".join(sig))

    calls = (props.get("call_sites") or [])[:MAX_CALLS]
    if calls:
        lines.append("Calls: " + ", ".join(calls))

    imports = (props.get("imports") or [])[:MAX_CALLS]
    if imports:
        lines.append("Imports: " + ", ".join(imports))

    children = skeleton.contains.get(node["id"], [])
    if children:
        child_lines = []
        for cid in children[:MAX_CHILDREN_CONTEXT]:
            cnode = skeleton.nodes.get(cid)
            if not cnode:
                continue
            summary = (enrichments.get(cid, {}) or {}).get("summary", "")
            cname = concept_name(cnode)
            child_lines.append(f"- {cnode['label']} {cname}: {summary}" if summary else f"- {cnode['label']} {cname}")
        if child_lines:
            lines.append("Contains:\n" + "\n".join(child_lines))

    return "\n".join(lines)


def _coerce_enrichment(raw: dict) -> dict:
    """Validate/normalize the model's JSON into the canonical enrichment shape."""
    def _s(v) -> str:
        return v.strip() if isinstance(v, str) else ""

    def _list_str(v) -> list[str]:
        if not isinstance(v, list):
            return []
        return [x.strip() for x in v if isinstance(x, str) and x.strip()]

    params = []
    if isinstance(raw.get("parameters"), list):
        for p in raw["parameters"]:
            if isinstance(p, dict) and _s(p.get("name")):
                params.append({"name": _s(p["name"]), "description": _s(p.get("description"))})

    return {
        "summary": _s(raw.get("summary"))[:300],
        "overview": _s(raw.get("overview")),
        "how_it_works": _s(raw.get("how_it_works")),
        "parameters": params,
        "tags": _list_str(raw.get("tags")),
        "related": _list_str(raw.get("related")),
    }


def fallback_enrichment(node: dict) -> dict:
    """Metadata-only page used on dry-run or when the model output is unusable."""
    props = node.get("properties", {}) or {}
    label = node.get("label", "concept")
    name = concept_name(node)
    vis = props.get("visibility")
    prefix = f"{vis} " if vis else ""
    if label == "File":
        summary = f"Source file `{name}`."
    else:
        summary = f"{prefix}{label.lower()} `{name}`.".strip()
    params = [{"name": p, "description": ""} for p in (props.get("parameters") or [])]
    return {
        "summary": summary,
        "overview": "",
        "how_it_works": "",
        "parameters": params,
        "tags": [t for t in (props.get("language"), props.get("visibility")) if t],
        "related": [],
    }


def _call_deepseek(client, model: str, system: str, user: str) -> dict:
    """One DeepSeek chat completion in JSON mode, parsed. Raises on failure."""
    resp = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        response_format={"type": "json_object"},
        max_tokens=_MAX_TOKENS,
        stream=False,
    )
    content = resp.choices[0].message.content or "{}"
    return json.loads(content)


def enrich_concept(client, model: str, node: dict, context: str, source: str) -> dict:
    """Enrich one concept; retry on transient/parse errors, then fall back."""
    user = (
        f"{context}\n\n"
        f"Source code:\n```\n{source}\n```\n\n"
        "Write the JSON wiki entry for this concept now."
    )
    last_exc: Optional[Exception] = None
    for attempt in range(_RETRIES):
        try:
            raw = _call_deepseek(client, model, SYSTEM_PROMPT, user)
            return _coerce_enrichment(raw)
        except json.JSONDecodeError as exc:
            last_exc = exc
            user += "\n\nYour previous reply was not valid JSON. Reply with a single valid JSON object only."
        except Exception as exc:  # network/rate-limit/etc.
            last_exc = exc
            time.sleep(min(2 ** attempt, 8))
    logger.warning("Enrichment failed for %s (%s); using fallback: %s", concept_name(node), model, last_exc)
    return fallback_enrichment(node)


def _ordered_ids(skeleton: Skeleton) -> list[list[str]]:
    """Group concept ids into bottom-up levels."""
    buckets: dict[int, list[str]] = {0: [], 1: [], 2: []}
    for nid in skeleton.concept_ids:
        node = skeleton.nodes.get(nid)
        if not node:
            continue
        buckets[_LEVEL.get(node["label"], 2)].append(nid)
    return [buckets[0], buckets[1], buckets[2]]


def enrich_all(
    skeleton: Skeleton,
    client,
    *,
    model_flash: str,
    model_pro: str,
    concurrency: int = 6,
    cache: Optional[dict[str, dict]] = None,
    force: bool = False,
    dry_run: bool = False,
    progress: Optional[Callable[[int, int], None]] = None,
) -> tuple[dict[str, dict], dict, dict]:
    """Enrich every concept bottom-up.

    Returns (enrichments, overview, updated_cache).
    - enrichments: concept id -> enrichment dict
    - overview: repo architecture page enrichment (empty on dry_run)
    - updated_cache: content-hash -> enrichment (persist for incremental re-runs)
    """
    cache = dict(cache or {})
    enrichments: dict[str, dict] = {}
    total = len(skeleton.concept_ids)
    done = 0

    def _one(nid: str) -> tuple[str, dict]:
        node = skeleton.nodes[nid]
        if dry_run:
            return nid, fallback_enrichment(node)
        key = okf_cache.concept_hash(node)
        if not force and key in cache:
            return nid, cache[key]
        context = _build_context(skeleton, node, enrichments)
        source = _read_source_slice(node)
        result = enrich_concept(client, model_flash, node, context, source)
        cache[key] = result
        return nid, result

    for level in _ordered_ids(skeleton):
        if not level:
            continue
        workers = 1 if dry_run else max(1, concurrency)
        with ThreadPoolExecutor(max_workers=workers) as pool:
            for nid, result in pool.map(_one, level):
                enrichments[nid] = result
                done += 1
                if progress:
                    progress(done, total)

    overview = _enrich_overview(skeleton, enrichments, client, model_pro, dry_run)
    return enrichments, overview, cache


def _enrich_overview(skeleton: Skeleton, enrichments: dict[str, dict], client, model_pro: str, dry_run: bool) -> dict:
    """Repo-level architecture summary (uses the higher-tier model)."""
    file_lines = []
    for nid in skeleton.concept_ids:
        node = skeleton.nodes.get(nid)
        if node and node["label"] == "File":
            summary = (enrichments.get(nid, {}) or {}).get("summary", "")
            file_lines.append(f"- {concept_name(node)}: {summary}" if summary else f"- {concept_name(node)}")
    if dry_run or not file_lines:
        return {
            "summary": f"Wiki for {Path(skeleton.repo_path).name}.",
            "overview": "",
            "how_it_works": "",
            "parameters": [],
            "tags": [],
            "related": [],
        }
    context = (
        f"Repository: {skeleton.repo_path}\n"
        f"Files and their summaries:\n" + "\n".join(file_lines[:200])
    )
    user = (
        f"{context}\n\n"
        "Write the JSON wiki entry for the WHOLE repository: a high-level architecture "
        "overview explaining what the system does and how the main pieces fit together."
    )
    try:
        raw = _call_deepseek(client, model_pro, SYSTEM_PROMPT, user)
        return _coerce_enrichment(raw)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Overview enrichment failed (%s); using minimal overview: %s", model_pro, exc)
        return {
            "summary": f"Wiki for {Path(skeleton.repo_path).name}.",
            "overview": "", "how_it_works": "", "parameters": [], "tags": [], "related": [],
        }
