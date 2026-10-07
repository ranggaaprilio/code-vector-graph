"""Application scoping in the MCP server (`repos` / `repo_roots`).

Two data situations must both work, and they scope differently:

* **recorded** — ingest stamped ``repo`` into the payload; the caller passes
  ``repos`` only and we push a ``repo MatchAny`` filter into Qdrant.
* **legacy** — no ``repo`` recorded; the caller also passes ``repo_roots`` and we
  over-fetch (``top_k * 3``) then post-filter on the ``file_path`` prefix.

All stores are replaced with fakes (`SimpleNamespace(records=[...])` for Neo4j,
matching the style of tests/api/conftest.py) — nothing here touches a service.
"""

import os
from types import SimpleNamespace

import pytest

pytest.importorskip("mcp")
pytest.importorskip("qdrant_client")

# The server module calls load_dotenv() at import; undo whatever it added so a
# developer's .env cannot leak into the rest of the suite.
_env_before = set(os.environ)
from code_vector_graph.mcp_server import server  # noqa: E402

for _key in set(os.environ) - _env_before:
    del os.environ[_key]
del _env_before

from qdrant_client.models import FieldCondition, Filter  # noqa: E402

ROOT_A = "/repos/onebid/backend_a"
ROOT_B = "/repos/onebid/backend_b"
ROOTS = [ROOT_A, ROOT_B]
REPOS = ["backend_a", "backend_b"]


# --------------------------------------------------------------------------- #
# Fakes
# --------------------------------------------------------------------------- #


class FakeEmbedder:
    def embed_query(self, query):
        return [0.1, 0.2, 0.3, 0.4]


class FakeStore:
    """Records the search() arguments and replays a fixed result list."""

    def __init__(self, results=None):
        self.results = list(results or [])
        self.calls = []

    def search(self, query_vector, top_k=10, query_filter=None):
        self.calls.append({"top_k": top_k, "query_filter": query_filter})
        return self.results[:top_k]

    @property
    def last(self):
        return self.calls[-1]


class FakeGraph:
    """Records every query_graph() call; answers from a scripted list of records."""

    def __init__(self, script=None):
        self.calls = []
        self.script = list(script or [])

    def query_graph(self, cypher, params=None):
        self.calls.append((cypher, dict(params or {})))
        records = self.script.pop(0) if self.script else []
        return SimpleNamespace(records=records)

    @property
    def last_cypher(self):
        return self.calls[-1][0]

    @property
    def last_params(self):
        return self.calls[-1][1]


def hit(idx, path, **payload):
    payload.setdefault("file_path", path)
    payload.setdefault("language", "javascript")
    payload.setdefault("text_content", f"code {idx}")
    return {"id": f"p{idx}", "payload": payload, "score": 1.0 - idx / 100}


@pytest.fixture
def wire(monkeypatch):
    """Install fakes for the three lazy singletons; return them."""

    def _wire(results=None, graph_script=None):
        embedder, store, graph = FakeEmbedder(), FakeStore(results), FakeGraph(graph_script)
        monkeypatch.setattr(server, "_get_embedder", lambda: embedder)
        monkeypatch.setattr(server, "_get_store", lambda: store)
        monkeypatch.setattr(server, "_get_graph_store", lambda: graph)
        return SimpleNamespace(embedder=embedder, store=store, graph=graph)

    return _wire


def _conditions(query_filter):
    """{key: condition} for the `must` conditions of a Qdrant filter."""
    return {c.key: c for c in (query_filter.must or []) if isinstance(c, FieldCondition)}


# --------------------------------------------------------------------------- #
# _repo_matches
# --------------------------------------------------------------------------- #


def test_repo_matches_no_scope_passes_everything():
    assert server._repo_matches({"file_path": "/somewhere/else/x.js"}) is True
    assert server._repo_matches({}, None, None) is True
    assert server._repo_matches({}, [], []) is True


def test_repo_matches_recorded_repo():
    payload = {"repo": "backend_a", "file_path": "/wherever/x.js"}
    assert server._repo_matches(payload, REPOS, ROOTS) is True


def test_repo_matches_recorded_foreign_repo_is_rejected():
    payload = {"repo": "some_other_repo", "file_path": f"{ROOT_A}/src/x.js"}
    assert server._repo_matches(payload, REPOS, ROOTS) is False


def test_repo_matches_legacy_prefix():
    assert server._repo_matches({"file_path": f"{ROOT_B}/src/x.js"}, REPOS, ROOTS) is True
    # Trailing slashes on the supplied roots must not change the answer.
    assert server._repo_matches({"file_path": f"{ROOT_B}/src/x.js"}, None, [ROOT_B + "/"]) is True


def test_repo_matches_legacy_sibling_prefix_is_not_a_match():
    # "/repos/onebid/backend_a_extra" must not match the root "/repos/onebid/backend_a".
    assert server._repo_matches({"file_path": f"{ROOT_A}_extra/src/x.js"}, REPOS, ROOTS) is False
    assert server._repo_matches({"file_path": "/other/app/src/x.js"}, REPOS, ROOTS) is False


def test_repo_matches_legacy_without_roots_cannot_match():
    assert server._repo_matches({"file_path": f"{ROOT_A}/src/x.js"}, REPOS, None) is False


def test_repo_matches_graph_node_path_property():
    # File/WikiPage graph nodes key the path as `path`, not `file_path`.
    assert server._repo_matches({"path": f"{ROOT_A}/src/x.js"}, REPOS, ROOTS) is True


def test_repo_matches_keeps_wiki_without_recorded_repo():
    # Wiki file_path is repo-relative, so no root prefix can ever match it; a wiki
    # page with no recorded repo carries no identity and must be kept, not dropped.
    wiki = {"source": server._WIKI_SOURCE, "file_path": "src/services/auth.md"}
    assert server._repo_matches(wiki, REPOS, ROOTS) is True
    assert server._repo_matches({"concept_id": "abc", "path": "index"}, REPOS, ROOTS) is True


def test_repo_matches_wiki_with_recorded_repo_is_filtered():
    wiki = {"source": server._WIKI_SOURCE, "repo": "some_other_repo", "file_path": "src/x.md"}
    assert server._repo_matches(wiki, REPOS, ROOTS) is False


# --------------------------------------------------------------------------- #
# _retrieve — vector mode
# --------------------------------------------------------------------------- #


def test_vector_recorded_scope_pushes_match_any_filter(wire):
    f = wire([hit(0, f"{ROOT_A}/src/a.js", repo="backend_a")])
    results = server._retrieve("q", mode="vector", top_k=5, repos=REPOS)

    call = f.store.last
    assert call["top_k"] == 5  # no over-fetch: the store did the filtering
    conds = _conditions(call["query_filter"])
    assert "repo" in conds
    assert list(conds["repo"].match.any) == REPOS
    assert len(results) == 1


def test_vector_legacy_scope_over_fetches_and_post_filters(wire):
    raw = [
        hit(0, f"{ROOT_A}/src/a.js"),
        hit(1, "/somewhere/else/b.js"),
        hit(2, f"{ROOT_B}/src/c.js"),
        hit(3, "/other/app/d.js"),
        hit(4, f"{ROOT_A}/src/e.js"),
        hit(5, f"{ROOT_B}/src/f.js"),
    ]
    f = wire(raw)
    results = server._retrieve("q", mode="vector", top_k=2, repos=REPOS, repo_roots=ROOTS)

    call = f.store.last
    assert call["top_k"] == 6  # top_k * 3
    # No hard `repo` filter — that would drop every legacy point.
    assert call["query_filter"] is None or "repo" not in _conditions(call["query_filter"])

    paths = [r["payload"]["file_path"] for r in results]
    assert paths == [f"{ROOT_A}/src/a.js", f"{ROOT_B}/src/c.js"]  # foreign paths gone, trimmed to top_k


def test_vector_unscoped_is_unchanged(wire):
    f = wire([hit(0, "/anywhere/a.js")])
    results = server._retrieve("q", mode="vector", top_k=3)
    assert f.store.last["top_k"] == 3
    assert f.store.last["query_filter"] is None
    assert len(results) == 1


def test_vector_scope_filter_coexists_with_language(wire):
    f = wire([hit(0, f"{ROOT_A}/src/a.js", repo="backend_a")])
    server._retrieve("q", mode="vector", top_k=5, language="typescript", repos=REPOS)
    conds = _conditions(f.store.last["query_filter"])
    assert set(conds) == {"language", "repo"}


# --------------------------------------------------------------------------- #
# _retrieve — hybrid mode
# --------------------------------------------------------------------------- #


def test_hybrid_recorded_scope_forwards_query_filter(wire):
    f = wire([hit(0, f"{ROOT_A}/src/a.js", repo="backend_a")])
    server._retrieve("q", mode="hybrid", top_k=4, repos=REPOS)

    call = f.store.last
    assert isinstance(call["query_filter"], Filter)
    assert list(_conditions(call["query_filter"])["repo"].match.any) == REPOS


def test_hybrid_legacy_scope_over_fetches_without_hard_filter(wire):
    raw = [hit(i, f"{ROOT_A}/src/{i}.js") for i in range(9)]
    f = wire(raw)
    results = server._retrieve("q", mode="hybrid", top_k=3, repos=REPOS, repo_roots=ROOTS)

    # HybridRetriever doubles the top_k it is given for its vector leg.
    assert f.store.last["top_k"] >= 9
    assert f.store.last["query_filter"] is None
    assert len(results) == 3


# --------------------------------------------------------------------------- #
# _retrieve — graph mode
# --------------------------------------------------------------------------- #


def _graph_records(*paths):
    return [
        {"id": f"n{i}", "node": {"id": f"n{i}", "name": "x", "path": p}, "score": 1.0}
        for i, p in enumerate(paths)
    ]


def test_graph_scope_params_and_cypher(wire):
    f = wire(graph_script=[_graph_records(f"{ROOT_A}/src/a.js", "/other/app/b.js")])
    results = server._retrieve("q", mode="graph", top_k=5, repos=REPOS, repo_roots=ROOTS)

    cypher, params = f.graph.calls[-1]
    assert params["repos"] == REPOS
    assert params["root_prefixes"] == [ROOT_A + "/", ROOT_B + "/"]
    assert params["limit"] == 15  # over-fetch, roots present
    assert "$repos IS NULL" in cypher
    assert "n.repo IN $repos" in cypher
    assert "any(p IN $root_prefixes WHERE n.path STARTS WITH p)" in cypher
    assert "EXISTS { MATCH (f:File)-[:CONTAINS|DEFINES]->(n)" in cypher

    # The Cypher scope is best-effort; the post-filter drops the foreign node.
    assert [r["payload"]["path"] for r in results] == [f"{ROOT_A}/src/a.js"]


def test_graph_unscoped_params_are_null(wire):
    f = wire(graph_script=[_graph_records("/anywhere/a.js")])
    results = server._retrieve("q", mode="graph", top_k=5)

    params = f.graph.last_params
    assert params["repos"] is None  # disables the scope branch entirely
    assert params["root_prefixes"] == []
    assert params["limit"] == 5
    assert len(results) == 1


def test_graph_recorded_only_scope_does_not_over_fetch(wire):
    f = wire(graph_script=[_graph_records(f"{ROOT_A}/src/a.js")])
    server._retrieve("q", mode="graph", top_k=5, repos=REPOS)
    assert f.graph.last_params["limit"] == 5
    assert f.graph.last_params["root_prefixes"] == []


# --------------------------------------------------------------------------- #
# _wiki_context
# --------------------------------------------------------------------------- #


def test_wiki_context_params_include_repo_and_rel(monkeypatch):
    graph = FakeGraph([[{"title": "auth.js", "summary": "Handles auth", "type": "File", "path": "src/auth.js"}]])
    monkeypatch.setattr(server, "_get_graph_store", lambda: graph)

    ctx = server._wiki_context(f"{ROOT_A}/src/auth.js", "login", "backend_a", "src/auth.js")

    cypher, params = graph.calls[-1]
    assert params == {
        "fp": f"{ROOT_A}/src/auth.js",
        "sym": "login",
        "repo": "backend_a",
        "rel": "src/auth.js",
    }
    assert "$repo IS NULL OR w.repo IS NULL OR w.repo = $repo" in cypher
    assert "split(w.resource, '#')[0] = $rel" in cypher
    assert ctx == {"title": "auth.js", "summary": "Handles auth", "type": "File", "path": "src/auth.js"}


def test_wiki_context_defaults_keep_legacy_behaviour(monkeypatch):
    graph = FakeGraph([[]])
    monkeypatch.setattr(server, "_get_graph_store", lambda: graph)

    assert server._wiki_context(f"{ROOT_A}/src/auth.js", "") is None
    assert graph.last_params == {"fp": f"{ROOT_A}/src/auth.js", "sym": "", "repo": None, "rel": ""}


# --------------------------------------------------------------------------- #
# search_code_json item shape
# --------------------------------------------------------------------------- #


def test_search_code_json_adds_identity_fields(wire):
    import json

    f = wire([hit(0, f"{ROOT_A}/src/a.js")])
    monkey_graph = f.graph
    monkey_graph.script.append([])  # _wiki_context finds nothing

    data = json.loads(
        server.search_code_json(
            "q", mode="vector", top_k=2, repos=REPOS, repo_roots=ROOTS
        )
    )
    item = data["results"][0]
    assert item["repo"] is None          # legacy point, nothing recorded
    assert item["app"] is None
    assert item["rel_path"] == "src/a.js"  # derived from the matching root
    assert item["file_path"] == f"{ROOT_A}/src/a.js"


def test_search_code_json_wiki_item_carries_concept_id(wire):
    import json

    wiki_payload = {
        "source": server._WIKI_SOURCE,
        "file_path": "src/auth.md",
        "symbol_id": "concept-123",
        "summary": "Auth overview",
        "term": "auth",
        "repo": "backend_a",
        "app": "onebid",
        "rel_path": "src/auth.md",
    }
    wire([{"id": "w1", "payload": wiki_payload, "score": 0.9}])

    data = json.loads(server.search_code_json("q", mode="vector", top_k=2, repos=REPOS))
    item = data["results"][0]
    assert item["source"] == "wiki"
    assert item["concept_id"] == "concept-123"
    assert item["repo"] == "backend_a"
    assert item["app"] == "onebid"
    assert item["rel_path"] == "src/auth.md"
