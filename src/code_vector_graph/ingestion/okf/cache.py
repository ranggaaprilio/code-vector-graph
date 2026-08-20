"""Incremental enrichment cache.

Each concept is keyed by a content hash (file hash + label + name + span). On a
re-run, concepts whose code is unchanged reuse their cached enrichment, so only
changed files hit the DeepSeek API. The cache lives inside the bundle
(`<out>/.okf-cache.json`) alongside the human-editable Markdown.
"""

from __future__ import annotations

import hashlib
import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

CACHE_FILENAME = ".okf-cache.json"


def concept_hash(node: dict) -> str:
    """Stable content key for a concept; changes when its code changes."""
    props = node.get("properties", {}) or {}
    fmeta = node.get("_file", {}) or {}
    file_hash = fmeta.get("file_hash") or props.get("file_hash", "")
    parts = [
        node.get("label", ""),
        props.get("name") or props.get("path") or props.get("term") or "",
        str(props.get("start_line", "")),
        str(props.get("end_line", "")),
        file_hash,
    ]
    return hashlib.sha256("::".join(parts).encode("utf-8")).hexdigest()[:16]


def load_cache(out_dir: str | Path) -> dict[str, dict]:
    path = Path(out_dir) / CACHE_FILENAME
    if not path.exists():
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("Ignoring unreadable OKF cache %s: %s", path, exc)
        return {}


def save_cache(out_dir: str | Path, cache: dict[str, dict]) -> None:
    path = Path(out_dir) / CACHE_FILENAME
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False, indent=2, sort_keys=True)
    tmp.replace(path)
