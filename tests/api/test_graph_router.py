"""Tests for /api/graph endpoints and the Cypher write guard."""

import pytest

pytest.importorskip("fastapi")

from code_vector_graph.api.routers.graph import _is_write_query  # noqa: E402

from .conftest import FakeNode, FakeRel  # noqa: E402


def test_subgraph_interpolates_depth_and_bounds_paths(client, fake_graph):
    f = FakeNode({"id": "f1", "path": "/repo/a.ts"}, labels=["File"])
    fn = FakeNode({"id": "fn1", "name": "doThing"}, labels=["Function"])
    fake_graph.queue([{"all_nodes": [f, fn], "all_rels": [FakeRel(f, fn, "DEFINES")]}])

    resp = client.get("/api/graph/subgraph", params={"node_id": "f1", "depth": 2, "limit": 50})
    assert resp.status_code == 200, resp.text

    cypher, params = fake_graph.calls[-1]
    assert "*1..2" in cypher
    assert "$depth" not in cypher and "depth" not in params
    assert "WITH path LIMIT $limit" in cypher
    assert params == {"node_id": "f1", "limit": 50}

    body = resp.json()
    assert {n["id"] for n in body["nodes"]} == {"f1", "fn1"}
    assert body["nodes"][0]["label"] == "File"
    assert body["edges"] == [
        {"id": body["edges"][0]["id"], "from": "f1", "to": "fn1", "type": "DEFINES"}
    ]


def test_subgraph_rejects_out_of_range_depth(client):
    assert client.get("/api/graph/subgraph", params={"node_id": "x", "depth": 4}).status_code == 422
    assert client.get("/api/graph/subgraph", params={"node_id": "x", "depth": 0}).status_code == 422


@pytest.mark.parametrize(
    "cypher",
    [
        "MATCH (n) RETURN n.offset",
        "MATCH (n {name:'set '}) RETURN n",
        'MATCH (n {name:"DELETE me"}) RETURN n',
        "MATCH (n:Function) WHERE n.name CONTAINS 'merge' RETURN n LIMIT 5",
        "CALL db.labels()",
        "CALL db.relationshipTypes() YIELD relationshipType RETURN relationshipType",
        "CALL apoc.meta.stats() YIELD labels RETURN labels",
        "MATCH (n) RETURN n.dataset, n.preset",
    ],
)
def test_is_write_query_allows_read_only(cypher):
    assert _is_write_query(cypher) is False


@pytest.mark.parametrize(
    "cypher",
    [
        "MATCH (n) SET n.x = 1",
        "match (n) set n.x = 1 return n",
        "CREATE (n:Foo) RETURN n",
        "MATCH (n) DETACH DELETE n",
        "MERGE (n:Foo {id: 1})",
        "MATCH (n) REMOVE n.x",
        "DROP INDEX foo",
        "LOAD CSV FROM 'file:///x.csv' AS row RETURN row",
        "CALL apoc.load.json('https://evil.example/x') YIELD value RETURN value",
        "CALL apoc.refactor.rename.label('A', 'B')",
        "CALL db.createLabel('X')",
        "MATCH (n) WITH n FOREACH (x IN [1] | SET n.y = x)",
    ],
)
def test_is_write_query_blocks_mutations(cypher):
    assert _is_write_query(cypher) is True


def test_cypher_endpoint_rejects_write(client):
    resp = client.post("/api/graph/cypher", json={"cypher": "MATCH (n) SET n.x = 1"})
    assert resp.status_code == 400
    assert "read-only" in resp.json()["detail"].lower()


def test_browse_nodes_unknown_label(client):
    assert client.get("/api/graph/nodes", params={"label": "Nope"}).status_code == 422
