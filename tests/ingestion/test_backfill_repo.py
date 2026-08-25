"""Tests for `cvg-backfill-repo` — stamping app/repo identity onto legacy data.

The Qdrant half runs against a real in-memory `QdrantClient`; the Neo4j half runs
against a fake that mimics the plain `query_graph()` duck type (no
`run_write_loop` convenience method), so `_run_write_loop`'s local fallback loop
is what gets exercised.
"""

from types import SimpleNamespace

import pytest
from qdrant_client import QdrantClient
from qdrant_client.models import Distance, PointStruct, VectorParams

from code_vector_graph.ingestion.backfill_repo import (
    BackfillOptions,
    build_plan,
    format_plan_table,
    run_backfill,
)

COLLECTION = "legacy_chunks"
REPOS_ROOT = "/Users/x/Repository"
GLOBAL_ROOT = f"{REPOS_ROOT}/onebid/backend/backend_nodejs_global_tnlm"
DATASYNC_ROOT = f"{REPOS_ROOT}/onebid/backend/backend_nodejs_data_sync_onebid"
GLOBAL = "backend_nodejs_global_tnlm"
DATASYNC = "backend_nodejs_data_sync_onebid"

CODE_POINTS = [
    (1, f"{GLOBAL_ROOT}/src/main.ts"),
    (2, f"{GLOBAL_ROOT}/src/main.ts"),  # second chunk of the same file
    (3, f"{GLOBAL_ROOT}/src/hubspot/hubspot.service.ts"),
    (4, f"{DATASYNC_ROOT}/src/hubspot-sync/scheduler.service.ts"),
]
WIKI_POINT_ID = 90
WIKI_SYMBOL_ID = "node-hubspot-service"


class FakeGraph:
    """A plain `query_graph(cypher, params)` duck type — no `run_write_loop`."""

    def __init__(self, symbol_repos: dict[str, dict] | None = None):
        self.calls: list[tuple[str, dict]] = []
        self.symbol_repos = symbol_repos or {}
        self._served: set[str] = set()

    def query_graph(self, cypher, params=None):
        params = dict(params or {})
        self.calls.append((cypher, params))

        if "UNWIND $ids" in cypher:
            rows = [
                {"cid": sid, **self.symbol_repos[sid]}
                for sid in params.get("ids", [])
                if sid in self.symbol_repos
            ]
            return SimpleNamespace(records=rows)

        if "MERGE (a:Application" in cypher:
            return SimpleNamespace(records=[{"id": params.get("rid")}])

        # The four write-loop queries all `RETURN count(...) AS n`; report the
        # work once per distinct (query, repo-or-rid), then 0 so the
        # `until count == 0` loop in `_run_write_loop` terminates.
        if "AS n" in cypher:
            key = f"{cypher}|{params.get('repo')}|{params.get('rid')}"
            if key not in self._served:
                self._served.add(key)
                return SimpleNamespace(records=[{"n": 3}])
            return SimpleNamespace(records=[{"n": 0}])
        return SimpleNamespace(records=[])

    def check_health(self):
        return True

    def close(self):
        return None

    def cyphers_matching(self, needle: str) -> list[str]:
        return [c for c, _ in self.calls if needle in c]


@pytest.fixture
def qdrant() -> QdrantClient:
    client = QdrantClient(":memory:")
    client.create_collection(
        collection_name=COLLECTION,
        vectors_config=VectorParams(size=4, distance=Distance.COSINE),
    )
    vec = [0.1, 0.2, 0.3, 0.4]
    points = [
        PointStruct(id=pid, vector=vec, payload={"file_path": path, "language": "typescript"})
        for pid, path in CODE_POINTS
    ]
    points.append(
        PointStruct(
            id=WIKI_POINT_ID,
            vector=vec,
            payload={
                # Wiki file_path is repo-relative, which is exactly why the repo
                # has to be resolved through the graph instead of a path prefix.
                "file_path": "src/hubspot/hubspot.service.ts",
                "source": "okf_wiki",
                "symbol_id": WIKI_SYMBOL_ID,
            },
        )
    )
    client.upsert(collection_name=COLLECTION, points=points)
    return client


@pytest.fixture
def graph() -> FakeGraph:
    return FakeGraph(
        symbol_repos={
            WIKI_SYMBOL_ID: {"repo": None, "path": f"{GLOBAL_ROOT}/src/hubspot/hubspot.service.ts"}
        }
    )


def options(qdrant, graph, **kw) -> BackfillOptions:
    return BackfillOptions(
        collection=COLLECTION,
        repos_root=REPOS_ROOT,
        client=qdrant,
        graph=graph,
        **kw,
    )


def payload_of(client: QdrantClient, point_id) -> dict:
    return client.retrieve(collection_name=COLLECTION, ids=[point_id], with_payload=True)[0].payload


# --------------------------------------------------------------------------- #
# Planning
# --------------------------------------------------------------------------- #


def test_build_plan_groups_two_repos_into_one_application():
    per_path = {path: 1 for _, path in CODE_POINTS}

    plan = build_plan(per_path, repos_root=REPOS_ROOT)

    assert {e.app for e in plan} == {"onebid"}
    by_repo = {e.repo: e for e in plan}
    assert set(by_repo) == {GLOBAL, DATASYNC}
    assert by_repo[GLOBAL].root == GLOBAL_ROOT
    assert by_repo[GLOBAL].files == 2  # main.ts + hubspot.service.ts
    assert by_repo[DATASYNC].files == 1


def test_build_plan_counts_points_not_just_files():
    per_path: dict[str, int] = {}
    for _pid, path in CODE_POINTS:
        per_path[path] = per_path.get(path, 0) + 1

    plan = build_plan(per_path, repos_root=REPOS_ROOT)

    assert {e.repo: e.points for e in plan}[GLOBAL] == 3  # two chunks of main.ts + one


def test_app_map_overrides_the_heuristic():
    per_path = {path: 1 for _, path in CODE_POINTS}

    plan = build_plan(per_path, app_map={"billing": [GLOBAL], "sync": [DATASYNC]})

    assert {e.repo: e.app for e in plan} == {GLOBAL: "billing", DATASYNC: "sync"}


def test_plan_table_renders_and_reports_empty():
    plan = build_plan({path: 1 for _, path in CODE_POINTS}, repos_root=REPOS_ROOT)

    table = format_plan_table(plan)
    assert "onebid" in table and GLOBAL in table and "APP" in table
    assert "2 repositories in 1 application(s)" in table

    assert "nothing to back-fill" in format_plan_table([])


# --------------------------------------------------------------------------- #
# Dry run
# --------------------------------------------------------------------------- #


def test_dry_run_plans_without_writing_anything(qdrant, graph):
    summary = run_backfill(options(qdrant, graph, dry_run=True))

    assert summary["dry_run"] is True
    assert {p["repo"] for p in summary["plan"]} == {GLOBAL, DATASYNC}
    assert summary["plan_table"]
    # Nothing stamped, no graph writes.
    assert "repo" not in payload_of(qdrant, 1)
    assert graph.calls == []


# --------------------------------------------------------------------------- #
# Full run
# --------------------------------------------------------------------------- #


def test_stamps_repo_app_and_root_onto_code_points(qdrant, graph):
    run_backfill(options(qdrant, graph))

    main = payload_of(qdrant, 1)
    assert main["repo"] == GLOBAL
    assert main["app"] == "onebid"
    assert main["repo_root"] == GLOBAL_ROOT
    # The original payload survives.
    assert main["file_path"] == f"{GLOBAL_ROOT}/src/main.ts"
    assert main["language"] == "typescript"

    assert payload_of(qdrant, 4)["repo"] == DATASYNC


def test_resolves_wiki_points_through_the_graph(qdrant, graph):
    summary = run_backfill(options(qdrant, graph))

    wiki = payload_of(qdrant, WIKI_POINT_ID)
    assert wiki["repo"] == GLOBAL
    assert wiki["app"] == "onebid"
    assert summary["qdrant"]["wiki_points"] == 1
    assert summary["qdrant"]["wiki_stamped"] == 1
    assert graph.cyphers_matching("UNWIND $ids")


def test_unresolvable_wiki_points_fall_back_to_wiki_repo(qdrant):
    empty_graph = FakeGraph(symbol_repos={})

    run_backfill(options(qdrant, empty_graph, wiki_repo=DATASYNC))

    assert payload_of(qdrant, WIKI_POINT_ID)["repo"] == DATASYNC


def test_unresolvable_wiki_points_without_fallback_are_reported(qdrant):
    empty_graph = FakeGraph(symbol_repos={})

    summary = run_backfill(options(qdrant, empty_graph))

    assert summary["qdrant"]["wiki_unresolved"] == 1
    assert "repo" not in payload_of(qdrant, WIKI_POINT_ID)


def test_creates_application_and_repository_nodes(qdrant, graph):
    summary = run_backfill(options(qdrant, graph))

    identity_calls = [p for c, p in graph.calls if "MERGE (a:Application" in c]
    assert len(identity_calls) == 2  # one per repo
    by_repo = {p["repo"]: p for p in identity_calls}
    assert by_repo[GLOBAL]["app"] == "onebid"
    assert by_repo[GLOBAL]["root"] == GLOBAL_ROOT

    assert summary["neo4j"]["applications"] == 1
    assert summary["neo4j"]["repositories"] == 2


def test_updates_files_chunks_and_wiki_pages_in_the_graph(qdrant, graph):
    summary = run_backfill(options(qdrant, graph))

    # Every write is guarded so a re-run is a no-op.
    assert any("f.repo IS NULL" in c for c in graph.cyphers_matching("MATCH (f:File)"))
    assert any("c.repo IS NULL" in c for c in graph.cyphers_matching("Chunk"))
    assert any("w.repo IS NULL" in c for c in graph.cyphers_matching("WikiPage"))

    assert summary["neo4j"]["files"] > 0
    assert summary["neo4j"]["chunks"] > 0
    assert summary["neo4j"]["wiki_pages"] > 0


def test_rerunning_stamps_nothing_new(qdrant, graph):
    run_backfill(options(qdrant, graph))
    second = run_backfill(options(qdrant, FakeGraph(symbol_repos=graph.symbol_repos)))

    # Everything already carries a repo, so there is nothing left to scan.
    assert second["plan"] == []
    assert second["qdrant"]["code_files"] == 0


# --------------------------------------------------------------------------- #
# Halves can be skipped
# --------------------------------------------------------------------------- #


def test_no_neo4j_skips_the_graph_half(qdrant, graph):
    summary = run_backfill(options(qdrant, graph, no_neo4j=True))

    assert payload_of(qdrant, 1)["repo"] == GLOBAL
    assert summary["neo4j"] == {}
    assert graph.calls == []


def test_no_qdrant_skips_the_payload_half(qdrant, graph):
    summary = run_backfill(options(qdrant, graph, no_qdrant=True))

    assert "repo" not in payload_of(qdrant, 1)
    assert summary["qdrant"] == {}


# --------------------------------------------------------------------------- #
# `_run_write_loop` delegates to `GraphStore.run_write_loop` when available
# --------------------------------------------------------------------------- #


def test_run_write_loop_prefers_the_graph_stores_native_loop():
    from code_vector_graph.ingestion.backfill_repo import _run_write_loop

    class GraphWithNativeLoop:
        def __init__(self):
            self.called_with = None

        def run_write_loop(self, cypher, params, key="n"):
            self.called_with = (cypher, params, key)
            return 42

        def query_graph(self, cypher, params=None):  # pragma: no cover - must not be used
            raise AssertionError("should have delegated to run_write_loop")

    g = GraphWithNativeLoop()
    total = _run_write_loop(g, "MATCH (n) RETURN count(n) AS n", {"a": 1})

    assert total == 42
    assert g.called_with == ("MATCH (n) RETURN count(n) AS n", {"a": 1}, "n")
