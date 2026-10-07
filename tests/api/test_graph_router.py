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


def test_edges_among_filters_to_visible_ids_and_dedupes(client, fake_graph):
    # Bare nodes, as the driver returns them when only `r` is in the RETURN:
    # element ids only, no `id` property. The endpoint must use from_id/to_id.
    a = FakeNode({}, labels=["Function"], element_id="4:x:1")
    b = FakeNode({}, labels=["Function"], element_id="4:x:2")
    rel = FakeRel(a, b, "CALLS", element_id="5:x:1")
    fake_graph.queue([
        {"r": rel, "from_id": "a", "to_id": "b"},
        {"r": rel, "from_id": "a", "to_id": "b"},
        {"r": None},
    ])

    resp = client.post("/api/graph/edges", json={"ids": ["b", "a", "", "a"]})
    assert resp.status_code == 200, resp.text

    cypher, params = fake_graph.calls[-1]
    assert "a.id IN $ids AND b.id IN $ids" in cypher
    assert "MATCH (a)-[r]->(b)" in cypher
    assert "a.id AS from_id, b.id AS to_id" in cypher
    assert params == {"ids": ["a", "b"], "limit": 500}
    assert resp.json() == {"edges": [{"id": "5:x:1", "from": "a", "to": "b", "type": "CALLS"}]}


def test_edges_among_short_circuits_on_empty_ids(client, fake_graph):
    resp = client.post("/api/graph/edges", json={"ids": []})
    assert resp.status_code == 200
    assert resp.json() == {"edges": []}
    assert fake_graph.calls == []


def test_edges_among_rejects_more_than_200_ids(client):
    resp = client.post("/api/graph/edges", json={"ids": [f"n{i}" for i in range(201)]})
    assert resp.status_code == 422


def test_cypher_relationship_cells_carry_endpoint_ids(client, monkeypatch, fake_graph):
    """The Visualize button needs start/end ids on relationship cells."""
    a = FakeNode({"id": "a", "name": "A"}, labels=["Function"])
    b = FakeNode({}, labels=["Chunk"], element_id="4:x:9")  # no id prop -> element id
    class MapRel(FakeRel, dict):
        """Real neo4j Relationships are Mappings of their properties; FakeRel is not."""

    rel = MapRel(a, b, "DOCUMENTS", element_id="5:x:7")

    class Rec(dict):
        def keys(self):
            return list(super().keys())

    class Session:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def execute_read(self, fn):
            return [Rec(n=a, r=rel, m=b)]

    class Driver:
        def session(self, **kw):
            assert kw.get("default_access_mode") == "READ"
            return Session()

    monkeypatch.setattr(type(fake_graph), "driver", property(lambda self: Driver()), raising=False)

    resp = client.post("/api/graph/cypher", json={"cypher": "MATCH (n)-[r]->(m) RETURN n, r, m"})
    assert resp.status_code == 200, resp.text
    row = resp.json()["rows"][0]
    assert row["r"]["_type"] == "relationship"
    assert row["r"]["start_node_id"] == "a"
    assert row["r"]["end_node_id"] == "4:x:9"
    assert row["m"]["_element_id"] == "4:x:9"
