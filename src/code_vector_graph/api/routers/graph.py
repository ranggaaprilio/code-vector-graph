"""Neo4j graph introspection and query endpoints."""

import logging
import re

from fastapi import APIRouter, Depends, HTTPException, Query

from code_vector_graph.api.deps import get_graph, get_registry
from code_vector_graph.api.schemas import CypherRequest
from code_vector_graph.api.serialize import serialize_value
from code_vector_graph.api.services.apps import ApplicationRegistry, AppScope
from code_vector_graph.stores.graph_schema import NODE_LABELS, RELATIONSHIP_TYPES
from code_vector_graph.stores.graph_store import GraphStore

# Application/Repository nodes are written by the ingest/backfill pipeline; they join
# graph_schema.NODE_LABELS in Phase 4 — accept them for browsing already.
BROWSE_LABELS = frozenset(NODE_LABELS | {"Application", "Repository"})

router = APIRouter(prefix="/graph")
logger = logging.getLogger(__name__)

# Best-effort guard for POST /graph/cypher. The real enforcement is the READ
# access mode + execute_read below; this only gives a friendlier 400 up front.
_STRING_LITERAL_RE = re.compile(r"'(?:[^'\\]|\\.)*'|\"(?:[^\"\\]|\\.)*\"")
_WRITE_KEYWORD_RE = re.compile(
    r"\b(create|merge|delete|detach|set|remove|drop|foreach)\b|\bload\s+csv\b",
    re.IGNORECASE,
)
_CALL_RE = re.compile(r"\bcall\s+([a-zA-Z_][\w.]*)", re.IGNORECASE)
# Read-only procedures the dashboard is allowed to CALL (prefix match).
_CALL_ALLOWLIST = (
    "db.labels",
    "db.relationshiptypes",
    "db.propertykeys",
    "db.schema.visualization",
    "apoc.meta.",
)


def _is_write_query(cypher: str) -> bool:
    """True if the Cypher looks like it mutates the graph or calls a non-allowlisted procedure."""
    stripped = _STRING_LITERAL_RE.sub("''", cypher)
    if _WRITE_KEYWORD_RE.search(stripped):
        return True
    for match in _CALL_RE.finditer(stripped):
        proc = match.group(1).lower()
        if not proc.startswith(_CALL_ALLOWLIST):
            return True
    return False


# Kept under the old name for existing imports; implementation lives in api/serialize.py.
_serialize_value = serialize_value


def _scope_or_404(registry: ApplicationRegistry, app: str | None, repo: str | None) -> AppScope | None:
    if not app:
        if repo:
            raise HTTPException(status_code=422, detail="`repo` requires `app`")
        return None
    try:
        return registry.scope(app, repo or None)
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


def _scoped_label_counts(graph: GraphStore, scope: AppScope) -> dict:
    labels: dict = {}
    for label in sorted(BROWSE_LABELS):
        where, params = scope.cypher_label_where(label, "n")
        try:
            r = graph.query_graph(f"MATCH (n:{label}) WHERE {where} RETURN count(n) AS cnt", params)
            recs = r.records if hasattr(r, "records") else list(r)
            labels[label] = recs[0].get("cnt", 0) if recs and hasattr(recs[0], "get") else 0
        except Exception:
            logger.debug("scoped count for %s failed", label, exc_info=True)
            labels[label] = 0
    return labels


@router.get("/stats")
def graph_stats(
    app: str | None = None,
    repo: str | None = None,
    graph: GraphStore = Depends(get_graph),
    registry: ApplicationRegistry = Depends(get_registry),
):
    labels: dict = {}
    rel_types: dict = {}
    scope = _scope_or_404(registry, app, repo)
    if scope is not None:
        labels = _scoped_label_counts(graph, scope)
        node_total = sum(int(v) for v in labels.values() if v)
        return {
            "labels": labels,
            "rel_types": {},
            "node_total": node_total,
            "rel_total": None,
            "scope": scope.label,
        }
    try:
        # Try APOC meta stats first
        result = graph.query_graph("CALL apoc.meta.stats() YIELD labels, relTypesCount")
        records = result.records if hasattr(result, "records") else list(result)
        if records:
            rec = records[0]
            labels = dict(rec.get("labels", {})) if hasattr(rec, "get") else {}
            rel_types = dict(rec.get("relTypesCount", {})) if hasattr(rec, "get") else {}
    except Exception:
        # Fallback: count each label individually
        for label in NODE_LABELS:
            try:
                r = graph.query_graph(f"MATCH (n:{label}) RETURN count(n) AS cnt")
                recs = r.records if hasattr(r, "records") else list(r)
                labels[label] = recs[0].get("cnt", 0) if recs and hasattr(recs[0], "get") else 0
            except Exception:
                labels[label] = 0
        for rel in RELATIONSHIP_TYPES:
            try:
                r = graph.query_graph(f"MATCH ()-[r:{rel}]->() RETURN count(r) AS cnt")
                recs = r.records if hasattr(r, "records") else list(r)
                rel_types[rel] = recs[0].get("cnt", 0) if recs and hasattr(recs[0], "get") else 0
            except Exception:
                rel_types[rel] = 0

    node_total = sum(int(v) for v in labels.values() if v)
    rel_total = sum(int(v) for v in rel_types.values() if v)
    return {
        "labels": labels,
        "rel_types": rel_types,
        "node_total": node_total,
        "rel_total": rel_total,
    }


@router.get("/nodes")
def browse_nodes(
    label: str = Query(..., description="Node label (e.g. Function, Class, File)"),
    limit: int = Query(default=50, le=200),
    skip: int = Query(default=0, ge=0),
    app: str | None = None,
    repo: str | None = None,
    graph: GraphStore = Depends(get_graph),
    registry: ApplicationRegistry = Depends(get_registry),
):
    if label not in BROWSE_LABELS:
        raise HTTPException(
            status_code=422,
            detail=f"Unknown label '{label}'. Valid: {sorted(BROWSE_LABELS)}",
        )
    scope = _scope_or_404(registry, app, repo)
    params: dict = {"skip": skip, "limit": limit}
    where = ""
    if scope is not None:
        clause, scope_params = scope.cypher_label_where(label, "n")
        where = f" WHERE {clause}"
        params.update(scope_params)
    try:
        result = graph.query_graph(
            f"MATCH (n:{label}){where} RETURN n SKIP $skip LIMIT $limit",
            params,
        )
        records = result.records if hasattr(result, "records") else list(result)
    except Exception as e:
        raise HTTPException(status_code=503, detail=str(e)) from e

    nodes = []
    for rec in records:
        node = rec.get("n") if hasattr(rec, "get") else None
        if node is None:
            continue
        props = {k: _serialize_value(v) for k, v in dict(node).items()}
        nodes.append({"id": props.get("id", str(getattr(node, "element_id", ""))), "properties": props})
    return {"label": label, "nodes": nodes, "skip": skip, "limit": limit, "scope": scope.label if scope else None}


@router.get("/subgraph")
def subgraph(
    node_id: str = Query(...),
    depth: int = Query(default=1, ge=1, le=3),
    limit: int = Query(default=100, le=200),
    graph: GraphStore = Depends(get_graph),
):
    try:
        # Variable-length bounds cannot be parameters in Cypher; `depth` is validated
        # to 1..3 above so interpolating it is safe. LIMIT bounds the number of paths
        # (before aggregation) so it actually caps the work done.
        cypher = (
            f"MATCH path = (n {{id: $node_id}})-[*1..{depth}]-(m) "
            "WITH path LIMIT $limit "
            "UNWIND nodes(path) AS node "
            "WITH collect(DISTINCT node) AS all_nodes, collect(path) AS paths "
            "UNWIND paths AS p "
            "UNWIND relationships(p) AS rel "
            "RETURN all_nodes, collect(DISTINCT rel) AS all_rels"
        )
        result = graph.query_graph(cypher, {"node_id": node_id, "limit": limit})
        records = result.records if hasattr(result, "records") else list(result)
    except Exception as e:
        raise HTTPException(status_code=503, detail=str(e)) from e

    seen_nodes: dict = {}
    seen_edges: dict = {}

    for rec in records:
        raw_nodes = rec.get("all_nodes") if hasattr(rec, "get") else []
        raw_rels = rec.get("all_rels") if hasattr(rec, "get") else []

        for node in (raw_nodes or []):
            props = {k: _serialize_value(v) for k, v in dict(node).items()}
            nid = props.get("id") or getattr(node, "element_id", None) or str(id(node))
            if nid not in seen_nodes:
                labels = list(node.labels) if hasattr(node, "labels") else []
                label = labels[0] if labels else "Node"
                caption = (
                    props.get("name") or props.get("path") or
                    props.get("function_name") or props.get("term") or
                    str(nid)[:20]
                )
                seen_nodes[nid] = {"id": nid, "label": label, "caption": caption, "properties": props}

        for rel in (raw_rels or []):
            eid = getattr(rel, "element_id", None) or str(id(rel))
            if eid not in seen_edges:
                start = getattr(rel, "start_node", None)
                end = getattr(rel, "end_node", None)
                start_props = {k: v for k, v in dict(start).items()} if start else {}
                end_props = {k: v for k, v in dict(end).items()} if end else {}
                seen_edges[eid] = {
                    "id": str(eid),
                    "from": start_props.get("id", str(getattr(start, "element_id", ""))),
                    "to": end_props.get("id", str(getattr(end, "element_id", ""))),
                    "type": rel.type if hasattr(rel, "type") else str(type(rel).__name__),
                }

    return {"nodes": list(seen_nodes.values()), "edges": list(seen_edges.values())}


@router.post("/cypher")
def run_cypher(req: CypherRequest, graph: GraphStore = Depends(get_graph)):
    if _is_write_query(req.cypher):
        raise HTTPException(status_code=400, detail="Write queries are not allowed. Use read-only Cypher.")

    # Cap limit in the params
    params = dict(req.params)
    limit = min(req.limit, 500)

    # Execute in a READ transaction via the raw driver
    driver = graph.driver
    try:
        with driver.session(default_access_mode="READ") as session:
            result = session.execute_read(
                lambda tx: list(tx.run(req.cypher, **params))
            )
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Cypher error: {e}") from e

    columns = list(result[0].keys()) if result else []
    rows = []
    truncated = False
    for i, rec in enumerate(result):
        if i >= limit:
            truncated = True
            break
        row = {}
        for col in columns:
            val = rec[col]
            if hasattr(val, "labels"):  # Neo4j Node
                row[col] = {
                    "_type": "node",
                    "_labels": list(val.labels),
                    "_element_id": str(val.element_id),
                    **{k: _serialize_value(v) for k, v in dict(val).items()},
                }
            elif hasattr(val, "type") and hasattr(val, "start_node"):  # Relationship
                row[col] = {
                    "_type": "relationship",
                    "_rel_type": val.type,
                    "_element_id": str(val.element_id),
                    **{k: _serialize_value(v) for k, v in dict(val).items()},
                }
            else:
                row[col] = _serialize_value(val)
        rows.append(row)

    return {"columns": columns, "rows": rows, "truncated": truncated}
