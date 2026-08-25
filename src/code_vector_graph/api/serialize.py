"""Helpers for turning Neo4j driver results into JSON-safe Python.

Shared by the routers and the application registry. Every helper tolerates the
test doubles used in ``tests/api`` (plain dicts / lists) as well as the real
driver types (``EagerResult``, ``Record``, ``Node``).
"""

from __future__ import annotations

from typing import Any


def serialize_value(v: Any) -> Any:
    """Convert Neo4j native types (Node, Relationship, Path, temporal…) to JSON-safe Python."""
    if hasattr(v, "items"):
        return {k: serialize_value(x) for k, x in dict(v).items()}
    if hasattr(v, "__iter__") and not isinstance(v, (str, bytes)):
        return [serialize_value(x) for x in v]
    if hasattr(v, "iso_format"):  # neo4j.time.DateTime and friends
        try:
            return v.iso_format()
        except Exception:  # pragma: no cover - defensive
            return str(v)
    return v


def records_of(result: Any) -> list:
    """``execute_query`` returns an ``EagerResult`` (``.records``); doubles return lists."""
    if result is None:
        return []
    recs = result.records if hasattr(result, "records") else result
    return list(recs)


def record_get(rec: Any, key: str, default: Any = None) -> Any:
    """Read a column from a neo4j ``Record`` or a plain dict."""
    if rec is None:
        return default
    if hasattr(rec, "get"):
        try:
            return rec.get(key, default)
        except Exception:  # pragma: no cover - defensive
            return default
    try:
        return rec[key]
    except Exception:
        return default


def node_props(node: Any) -> dict:
    """Properties of a neo4j ``Node`` (or dict) as a JSON-safe dict."""
    if node is None:
        return {}
    if hasattr(node, "items"):
        return {k: serialize_value(v) for k, v in dict(node).items()}
    return {}


def node_label(node: Any, default: str = "Node") -> str:
    labels = list(getattr(node, "labels", []) or [])
    return labels[0] if labels else default


def node_id(node: Any) -> str | None:
    props = node_props(node)
    nid = props.get("id")
    if nid:
        return str(nid)
    eid = getattr(node, "element_id", None)
    return str(eid) if eid else None


def scalar(result: Any, key: str, default: Any = 0) -> Any:
    """First record's ``key`` column (typical for ``RETURN count(x) AS key``)."""
    recs = records_of(result)
    if not recs:
        return default
    value = record_get(recs[0], key, default)
    return default if value is None else value
