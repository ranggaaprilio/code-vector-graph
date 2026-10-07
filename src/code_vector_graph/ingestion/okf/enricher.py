"""LLM enrichment agent — writes plain-language wiki content per concept.

The agent walks the skeleton bottom-up (leaf functions/methods -> classes ->
files), reads each concept's source plus its grounded neighbors, and asks the
model for a structured JSON page (summary, overview, how-it-works, params,
tags, related). Higher-level concepts receive their children's one-line
summaries so their pages stay coherent (the DeepWiki pattern).

Two providers are supported, selected by ``OKF_LLM_PROVIDER`` (see config.py):

- ``deepseek`` — the DeepSeek cloud API (default).
- ``omlx``     — a local oMLX server (or any OpenAI-compatible local endpoint)
  running e.g. Gemma/Qwen fully offline.

Both are OpenAI-compatible, so the `openai` SDK (already a dependency) is
pointed at the provider's base URL. Structured output uses JSON mode
(`response_format={"type": "json_object"}`) with the schema described in the
system prompt, validated/repaired in Python. Small local models occasionally
wrap the JSON in a Markdown code fence, which `_parse_json_reply` tolerates.
"""

from __future__ import annotations

import json
import logging
import re
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Callable, Optional

from code_vector_graph.config import okf_llm_settings
from code_vector_graph.ingestion.okf import cache as okf_cache
from code_vector_graph.ingestion.okf.skeleton import Skeleton, concept_name

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


def make_client(api_key: Optional[str] = None, base_url: Optional[str] = None,
                provider: Optional[str] = None, *, probe: Optional[bool] = None):
    """Construct an OpenAI-SDK client for the configured enrichment provider.

    With no arguments everything is resolved from the environment via
    ``okf_llm_settings()`` (``OKF_LLM_PROVIDER`` = deepseek | omlx). Explicit
    ``api_key``/``base_url`` override the resolved values.

    For a local provider (oMLX) the server is probed once (``GET /v1/models``)
    so a stopped server or a wrong key fails fast with a clear message instead
    of every concept silently falling back to a metadata-only page. Pass
    ``probe=False`` to skip that (e.g. from the dashboard API startup).

    Raises ``ValueError`` with an actionable message when misconfigured.
    """
    from openai import OpenAI  # imported lazily so tests can run without the dep loaded

    s = okf_llm_settings()
    provider = provider or s.provider
    api_key = api_key if api_key is not None else s.api_key
    base_url = base_url or s.base_url
    local = provider == "omlx"

    if not api_key:
        if local:
            # oMLX can run with API-key verification disabled; the SDK still
            # needs a non-empty string. If the server does require a key the
            # probe below reports it.
            api_key = "omlx"
        else:
            raise ValueError(
                f"{s.key_env} is not set. Add it to your environment or .env "
                "(see .env.example), or set OKF_LLM_PROVIDER=omlx to use a local oMLX server."
            )

    client = OpenAI(api_key=api_key, base_url=base_url)

    do_probe = local if probe is None else probe
    if do_probe:
        try:
            models = [m.id for m in client.models.list().data]
        except Exception as exc:  # noqa: BLE001 — surface *any* connection/auth problem
            status = getattr(exc, "status_code", None)
            hint = (
                f"{s.key_env} is missing or wrong (server returned 401)" if status == 401
                else f"is the server running at {base_url}? ({type(exc).__name__}: {exc})"
            )
            raise ValueError(f"Cannot reach the {provider} server: {hint}") from exc
        for wanted in {s.model_flash, s.model_pro}:
            if models and wanted not in models:
                raise ValueError(
                    f"Model '{wanted}' is not served by {provider} at {base_url}. "
                    f"Available: {', '.join(models)}. Set OMLX_MODEL / OKF_MODEL_FLASH / OKF_MODEL_PRO."
                )
    return client


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


_FENCE_RE = re.compile(r"^\s*```(?:json|JSON)?\s*\n?(.*?)\n?\s*```\s*$", re.DOTALL)


def _parse_json_reply(content: str) -> dict:
    """Parse the model's JSON reply, tolerating a Markdown code fence or
    stray prose around the object (common with small local models).

    Raises ``json.JSONDecodeError`` if no JSON object can be recovered.
    """
    text = (content or "").strip()
    if not text:
        raise json.JSONDecodeError("Empty reply", content or "", 0)
    m = _FENCE_RE.match(text)
    if m:
        text = m.group(1).strip()
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        start, end = text.find("{"), text.rfind("}")
        if start == -1 or end <= start:
            raise
        parsed = json.loads(text[start:end + 1])
    if not isinstance(parsed, dict):
        raise json.JSONDecodeError("Reply is not a JSON object", text, 0)
    return parsed


def _provider_extra_body(provider: str, *, thinking: bool) -> dict:
    """Provider-specific request fields controlling reasoning/thinking mode."""
    if provider == "omlx":
        # oMLX forwards `chat_template_kwargs` to the model's chat template;
        # `enable_thinking` is honoured by Qwen3-style templates and ignored by
        # models without a thinking mode (Gemma).
        return {"chat_template_kwargs": {"enable_thinking": thinking}}
    return {"thinking": {"type": "enabled" if thinking else "disabled"}}


def _call_llm(
    client,
    model: str,
    system: str,
    user: str,
    max_tokens: int = _MAX_TOKENS,
    *,
    thinking: bool = False,
    reasoning_effort: Optional[str] = None,
    provider: Optional[str] = None,
) -> dict:
    """One chat completion in JSON mode, parsed. Raises on failure.

    ``provider`` defaults to ``OKF_LLM_PROVIDER`` and only changes the
    provider-specific ``extra_body`` (see `_provider_extra_body`).

    Thinking mode is **disabled by default**: DeepSeek V4 models think by
    default (effort "high"), and the reasoning tokens count against
    `max_tokens`. With the tight budgets used here (1.5k-8k) the model spent
    ~90% of the budget thinking and the JSON answer came back truncated
    (`finish_reason="length"`), which every caller then treated as a failure
    and silently replaced with a structural fallback. The same applies to local
    thinking models (Qwen3) behind oMLX. Pass `thinking=True` (optionally with
    `reasoning_effort="low"|"high"|"max"`, DeepSeek only) to opt back in.
    """
    provider = provider or okf_llm_settings().provider
    kwargs: dict = {}
    if thinking and reasoning_effort and provider == "deepseek":
        kwargs["reasoning_effort"] = reasoning_effort
    resp = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        response_format={"type": "json_object"},
        max_tokens=max_tokens,
        stream=False,
        extra_body=_provider_extra_body(provider, thinking=thinking),
        **kwargs,
    )
    choice = resp.choices[0]
    content = choice.message.content or "{}"
    if getattr(choice, "finish_reason", None) == "length":
        # Surface truncation as a parse-class error so callers' retry paths
        # see a clear reason instead of a bare "Unterminated string".
        raise json.JSONDecodeError(
            f"{provider} reply truncated at max_tokens={max_tokens} (finish_reason=length)", content, len(content)
        )
    return _parse_json_reply(content)


# Backwards-compatible name (the function is provider-agnostic now).
_call_deepseek = _call_llm


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
            raw = _call_llm(client, model, SYSTEM_PROMPT, user)
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
        raw = _call_llm(client, model_pro, SYSTEM_PROMPT, user)
        return _coerce_enrichment(raw)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Overview enrichment failed (%s); using minimal overview: %s", model_pro, exc)
        return {
            "summary": f"Wiki for {Path(skeleton.repo_path).name}.",
            "overview": "", "how_it_works": "", "parameters": [], "tags": [], "related": [],
        }
