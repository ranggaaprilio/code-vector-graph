"""Neo4j graph introspection and query endpoints."""

import logging

from fastapi import APIRouter, Depends, HTTPException, Query
from neo4j import GraphDatabase

from dashboard.deps import get_graph
from dashboard.schemas import CypherRequest
from dashboard.settings import NEO4J_PASSWORD, NEO4J_URI, NEO4J_USER
from src.graph_schema import NODE_LABELS, RELATIONSHIP_TYPES
from src.graph_store import GraphStore

router = APIRouter(prefix="/graph")
logger = logging.getLogger(__name__)

_WRITE_KEYWORDS = (
    "create ", "merge ", "delete ", "detach ", "set ", "remove ",
    "drop ", "call apoc.refactor", "call apoc.create", "call apoc.merge",
    "call db.create", "call db.index",
)


def _is_write_query(cypher: str) -> bool:
    lower = cypher.lower()
    return any(kw in lower for kw in _WRITE_KEYWORDS)


def _serialize_value(v):
    """Convert Neo4j native types to JSON-safe Python."""
    if hasattr(v, "items"):
        return dict(v)
    if hasattr(v, "__iter__") and not isinstance(v, (str, bytes)):
        return list(v)
    return v


@router.get("/stats")
def graph_stats(graph: GraphStore = Depends(get_graph)):
    labels: dict = {}
    rel_types: dict = {}
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
    graph: GraphStore = Depends(get_graph),
):
    if label not in NODE_LABELS:
        raise HTTPException(
            status_code=422,
            detail=f"Unknown label '{label}'. Valid: {sorted(NODE_LABELS)}",
        )
    try:
        result = graph.query_graph(
            f"MATCH (n:{label}) RETURN n SKIP $skip LIMIT $limit",
            {"skip": skip, "limit": limit},
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
    return {"label": label, "nodes": nodes, "skip": skip, "limit": limit}


@router.get("/subgraph")
def subgraph(
    node_id: str = Query(...),
    depth: int = Query(default=1, ge=1, le=3),
    limit: int = Query(default=100, le=200),
    graph: GraphStore = Depends(get_graph),
):
    try:
        cypher = (
            "MATCH path = (n {id: $node_id})-[*1..$depth]-(m) "
            "WITH nodes(path) AS ns, relationships(path) AS rs "
            "UNWIND ns AS node "
            "WITH collect(DISTINCT node) AS all_nodes, rs "
            "UNWIND rs AS rel "
            "RETURN all_nodes, collect(DISTINCT rel) AS all_rels "
            "LIMIT $limit"
        )
        result = graph.query_graph(cypher, {"node_id": node_id, "depth": depth, "limit": limit})
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
