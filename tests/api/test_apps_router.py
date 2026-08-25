"""Tests for the application-centric `/api/apps` endpoints.

The graph is faked with a *pattern-matching* stand-in rather than the ordered
script used elsewhere: `app_detail` fires a dozen queries whose order is an
implementation detail, and asserting on it would make these tests brittle.
"""

import pytest

pytest.importorskip("fastapi")

from types import SimpleNamespace  # noqa: E402

from fastapi.testclient import TestClient  # noqa: E402

from code_vector_graph.api.app import app as fastapi_app  # noqa: E402
from code_vector_graph.api.deps import get_graph, get_qdrant, get_registry  # noqa: E402
from code_vector_graph.api.services.apps import (  # noqa: E402
    AppInfo,
    ApplicationRegistry,
    FileEntry,
)

from .conftest import (  # noqa: E402
    ONEBID_ROOTS,
    REPOS_ROOT,
    FakeNode,
    StubRegistry,
    make_repo,
)

GLOBAL = "backend_nodejs_global_tnlm"
DATASYNC = "backend_nodejs_data_sync_onebid"


class PatternGraph:
    """Answers `query_graph` from the first matching (substring, records) rule."""

    def __init__(self):
        self.rules: list[tuple[str, list]] = []
        self.calls: list[tuple[str, dict]] = []
        self.healthy = True

    def on(self, needle: str, records: list) -> "PatternGraph":
        self.rules.append((needle, records))
        return self

    def query_graph(self, cypher, params=None):
        self.calls.append((cypher, dict(params or {})))
        for needle, records in self.rules:
            if needle in cypher:
                return SimpleNamespace(records=list(records))
        return SimpleNamespace(records=[])

    def check_health(self):
        return self.healthy

    def cypher_for(self, needle: str) -> tuple[str, dict] | None:
        for cypher, params in self.calls:
            if needle in cypher:
                return cypher, params
        return None


@pytest.fixture
def pattern_graph() -> PatternGraph:
    return PatternGraph()


@pytest.fixture
def apps_client(pattern_graph, fake_qdrant, stub_registry):
    """Client whose graph answers by pattern; registry is the two-repo onebid stub."""
    fastapi_app.dependency_overrides[get_graph] = lambda: pattern_graph
    fastapi_app.dependency_overrides[get_qdrant] = lambda: fake_qdrant
    fastapi_app.dependency_overrides[get_registry] = lambda: stub_registry
    try:
        yield TestClient(fastapi_app)
    finally:
        fastapi_app.dependency_overrides.clear()


def file_entry(repo: str, rel: str, **kw) -> FileEntry:
    return FileEntry(
        id=kw.pop("id", f"{repo}:{rel}"),
        path=f"{ONEBID_ROOTS[repo]}/{rel}",
        rel_path=rel,
        repo=repo,
        language=kw.pop("language", "typescript"),
        line_count=kw.pop("line_count", 42),
        **kw,
    )


# --------------------------------------------------------------------------- #
# Registry discovery (real logic, fake stores)
# --------------------------------------------------------------------------- #


def test_registry_derives_one_app_from_two_legacy_repo_paths(fake_graph, fake_qdrant):
    """Legacy File paths under a shared repos_root collapse into one application."""
    fake_graph.queue([])  # recorded: no Application/Repository nodes yet
    fake_graph.queue(
        [
            {"path": f"{ONEBID_ROOTS[GLOBAL]}/src/a.ts", "language": "typescript"},
            {"path": f"{ONEBID_ROOTS[GLOBAL]}/src/b.ts", "language": "typescript"},
            {"path": f"{ONEBID_ROOTS[DATASYNC]}/src/c.ts", "language": "typescript"},
        ]
    )
    registry = ApplicationRegistry(
        graph=fake_graph,
        qdrant=fake_qdrant,
        collection="test_collection",
        ttl=0,
        repos_root=REPOS_ROOT,
    )

    apps = registry.list()

    assert [a.name for a in apps] == ["onebid"]
    onebid = apps[0]
    assert sorted(r.name for r in onebid.repos) == sorted([DATASYNC, GLOBAL])
    assert all(r.source == "derived" for r in onebid.repos)
    assert onebid.source == "derived"


def test_registry_scope_narrows_to_one_repo(stub_registry):
    scope = stub_registry.scope("onebid")
    assert sorted(scope.repo_names) == sorted([DATASYNC, GLOBAL])
    assert scope.label == "onebid · all repos"

    narrowed = stub_registry.scope("onebid", GLOBAL)
    assert narrowed.repo_names == [GLOBAL]
    assert narrowed.label == f"onebid · {GLOBAL}"

    with pytest.raises(KeyError):
        stub_registry.scope("onebid", "nope")
    with pytest.raises(KeyError):
        stub_registry.scope("nope")


# --------------------------------------------------------------------------- #
# GET /api/apps
# --------------------------------------------------------------------------- #


def test_list_apps_returns_app_with_its_repos(apps_client):
    resp = apps_client.get("/api/apps")

    assert resp.status_code == 200
    body = resp.json()
    assert [a["name"] for a in body["apps"]] == ["onebid"]
    repos = body["apps"][0]["repos"]
    assert sorted(r["name"] for r in repos) == sorted([DATASYNC, GLOBAL])
    assert repos[0]["root"].startswith(REPOS_ROOT)


def test_refresh_apps_endpoint(apps_client):
    assert apps_client.post("/api/apps/refresh").status_code == 200


# --------------------------------------------------------------------------- #
# GET /api/apps/{app}
# --------------------------------------------------------------------------- #


def test_app_detail_reports_counts_and_fallback_overview(apps_client, pattern_graph, stub_registry):
    pattern_graph.on("labels(s)[0]", [{"label": "Function", "n": 7}, {"label": "Class", "n": 2}])
    stub_registry.files_by_key[("onebid", GLOBAL)] = [
        file_entry(GLOBAL, "src/hubspot/hubspot.service.ts"),
        file_entry(GLOBAL, "src/webhooks/webhooks.controller.ts"),
        file_entry(GLOBAL, "test/app.e2e-spec.ts"),
    ]

    resp = apps_client.get("/api/apps/onebid")

    assert resp.status_code == 200
    body = resp.json()
    assert body["app"]["name"] == "onebid"
    repos = {r["name"]: r for r in body["repos"]}
    assert set(repos) == {GLOBAL, DATASYNC}

    # No WikiPage rows scripted -> every repo falls back to a statistics overview
    # carrying the hint that tells the user how to generate the real one.
    overview = repos[GLOBAL]["overview"]
    assert overview["source"] == "fallback"
    assert "cvg-okf-build" in (overview.get("hint") or "")

    top = [m["path"] for m in repos[GLOBAL]["top_modules"]]
    assert "src" in top and "test" in top


REPO_PAGE_PROPS = {
    "concept_id": "repo-id",
    "title": "onebid backend",
    "type": "Repository",
    "summary": "NestJS services syncing HubSpot data.",
    "overview": "## Architecture\n\nTwo services.",
    "how_it_works": "Kafka topics bridge them.",
    "repo": GLOBAL,
    "path": "index",
    "resource": "",
}


def test_app_detail_uses_wiki_overview_when_present(apps_client, pattern_graph):
    # `_repo_overview` does `RETURN w` (a node); the wiki_top listing returns scalars.
    pattern_graph.on(
        "MATCH (w:WikiPage {type:'Repository'})",
        [{"w": FakeNode(REPO_PAGE_PROPS, labels=["WikiPage"])}],
    )
    pattern_graph.on("w:WikiPage", [dict(REPO_PAGE_PROPS)])

    body = apps_client.get("/api/apps/onebid").json()

    repos = {r["name"]: r for r in body["repos"]}
    assert repos[GLOBAL]["overview"]["source"] == "wiki"
    assert "Two services" in repos[GLOBAL]["overview"]["overview"]
    assert body["wiki_top"][0]["title"] == "onebid backend"


def test_app_detail_unknown_app_is_404(apps_client):
    assert apps_client.get("/api/apps/nope").status_code == 404


def test_app_detail_survives_a_failing_graph(apps_client, pattern_graph):
    def boom(cypher, params=None):
        raise RuntimeError("neo4j down")

    pattern_graph.query_graph = boom

    resp = apps_client.get("/api/apps/onebid")

    # Degraded, not fatal: the app and its repos still come back.
    assert resp.status_code == 200
    assert resp.json()["app"]["name"] == "onebid"


# --------------------------------------------------------------------------- #
# GET /api/apps/{app}/tree
# --------------------------------------------------------------------------- #


def test_tree_without_repo_lists_the_repositories(apps_client):
    body = apps_client.get("/api/apps/onebid/tree").json()

    assert body["kind"] == "repos"
    assert sorted(r["name"] for r in body["repos"]) == sorted([DATASYNC, GLOBAL])


def test_tree_lists_dirs_and_files_at_a_path(apps_client, stub_registry):
    stub_registry.files_by_key[("onebid", GLOBAL)] = [
        file_entry(GLOBAL, "src/main.ts"),
        file_entry(GLOBAL, "src/hubspot/hubspot.service.ts"),
        file_entry(GLOBAL, "src/hubspot/hubspot.controller.ts"),
        file_entry(GLOBAL, "src/webhooks/webhooks.service.ts"),
    ]

    root = apps_client.get(f"/api/apps/onebid/tree?repo={GLOBAL}").json()
    assert root["kind"] == "dir"
    assert [d["name"] for d in root["dirs"]] == ["src"]
    assert root["dirs"][0]["file_count"] == 4
    assert root["files"] == []

    src = apps_client.get(f"/api/apps/onebid/tree?repo={GLOBAL}&path=src").json()
    assert [d["name"] for d in src["dirs"]] == ["hubspot", "webhooks"]
    assert [f["name"] for f in src["files"]] == ["main.ts"]
    assert src["files"][0]["path"] == "src/main.ts"
    assert src["files"][0]["abs_path"].startswith(ONEBID_ROOTS[GLOBAL])


def test_tree_unknown_dir_is_404(apps_client, stub_registry):
    stub_registry.files_by_key[("onebid", GLOBAL)] = [file_entry(GLOBAL, "src/main.ts")]

    resp = apps_client.get(f"/api/apps/onebid/tree?repo={GLOBAL}&path=nope")

    assert resp.status_code == 404


def test_tree_unknown_repo_is_404(apps_client):
    assert apps_client.get("/api/apps/onebid/tree?repo=nope").status_code == 404


# --------------------------------------------------------------------------- #
# GET /api/apps/{app}/files/{repo}/{path}
# --------------------------------------------------------------------------- #


def test_file_detail_merges_symbols_and_qdrant_chunks(apps_client, pattern_graph, fake_qdrant):
    from qdrant_client.models import Distance, PointStruct, VectorParams

    from code_vector_graph.api.config import QDRANT_COLLECTION

    abs_path = f"{ONEBID_ROOTS[GLOBAL]}/src/main.ts"
    fake_qdrant.recreate_collection(
        collection_name=QDRANT_COLLECTION,
        vectors_config=VectorParams(size=4, distance=Distance.COSINE),
    )
    fake_qdrant.upsert(
        collection_name=QDRANT_COLLECTION,
        points=[
            PointStruct(
                id=1,
                vector=[0.1, 0.2, 0.3, 0.4],
                payload={
                    "file_path": abs_path,
                    "chunk_index": 1,
                    "start_line": 10,
                    "end_line": 20,
                    "text_content": "export function bootstrap() {}",
                    "function_name": "bootstrap",
                },
            ),
            PointStruct(
                id=2,
                vector=[0.1, 0.2, 0.3, 0.4],
                payload={
                    "file_path": abs_path,
                    "chunk_index": 0,
                    "start_line": 1,
                    "end_line": 9,
                    "text_content": "import { NestFactory } from '@nestjs/core';",
                },
            ),
            PointStruct(  # wiki prose for the same path must not leak into chunks
                id=3,
                vector=[0.1, 0.2, 0.3, 0.4],
                payload={"file_path": abs_path, "source": "okf_wiki", "text_content": "prose"},
            ),
        ],
    )

    file_node = {"id": "file-1", "path": abs_path, "language": "typescript", "line_count": 30}
    pattern_graph.on("MATCH (f:File)", [{"f": file_node}])
    pattern_graph.on(
        "DEFINES",
        [
            {
                "s": {"id": "fn-1", "name": "bootstrap", "start_line": 10, "end_line": 20},
                "label": "Function",
                "w": None,
            }
        ],
    )

    resp = apps_client.get(f"/api/apps/onebid/files/{GLOBAL}/src/main.ts")

    assert resp.status_code == 200
    body = resp.json()
    assert body["file"]["path"] == abs_path
    assert [s["name"] for s in body["symbols"]] == ["bootstrap"]
    # Sorted by chunk_index, wiki point excluded.
    assert [c["start_line"] for c in body["chunks"]] == [1, 10]
    assert all(c["text_content"] != "prose" for c in body["chunks"])


def test_file_detail_unknown_file_is_404(apps_client, pattern_graph):
    pattern_graph.on("MATCH (f:File)", [])

    resp = apps_client.get(f"/api/apps/onebid/files/{GLOBAL}/src/nope.ts")

    assert resp.status_code == 404


# --------------------------------------------------------------------------- #
# Wiki endpoints
# --------------------------------------------------------------------------- #


def test_wiki_list_and_page(apps_client, pattern_graph):
    page = {
        "concept_id": "c-1",
        "title": "HubspotService",
        "type": "Class",
        "summary": "Upserts HubSpot records.",
        "overview": "Detail.",
        "how_it_works": "Steps.",
        "repo": GLOBAL,
        "path": "class/hubspotservice-ab12",
        "resource": "src/hubspot/hubspot.service.ts",
        "tags": ["typescript"],
    }
    # The page endpoint returns the node itself; the listing returns scalar columns.
    pattern_graph.on(
        "w.concept_id = $cid",
        [
            {
                "w": FakeNode(page, labels=["WikiPage"]),
                "n": None,
                "label": None,
                "file_path": None,
            }
        ],
    )
    pattern_graph.on("w:WikiPage", [dict(page)])

    listing = apps_client.get("/api/apps/onebid/wiki").json()
    assert listing["pages"][0]["title"] == "HubspotService"

    detail = apps_client.get("/api/apps/onebid/wiki/c-1")
    assert detail.status_code == 200
    assert detail.json()["page"]["title"] == "HubspotService"


def test_wiki_page_unknown_concept_is_404(apps_client, pattern_graph):
    pattern_graph.on("w:WikiPage", [])

    assert apps_client.get("/api/apps/onebid/wiki/nope").status_code == 404


# --------------------------------------------------------------------------- #
# Empty index
# --------------------------------------------------------------------------- #


def test_no_applications_yields_an_empty_list(pattern_graph, fake_qdrant):
    empty = StubRegistry(apps=[])
    fastapi_app.dependency_overrides[get_graph] = lambda: pattern_graph
    fastapi_app.dependency_overrides[get_qdrant] = lambda: fake_qdrant
    fastapi_app.dependency_overrides[get_registry] = lambda: empty
    try:
        client = TestClient(fastapi_app)
        assert client.get("/api/apps").json()["apps"] == []
        assert client.get("/api/apps/onebid").status_code == 404
    finally:
        fastapi_app.dependency_overrides.clear()


def test_aggregate_rolls_repo_counts_up_to_the_app():
    info = AppInfo.aggregate(
        "onebid",
        [
            make_repo(GLOBAL, file_count=10, chunk_count=100, languages={"typescript": 10}),
            make_repo(
                DATASYNC,
                file_count=5,
                chunk_count=40,
                languages={"typescript": 4, "javascript": 1},
            ),
        ],
    )

    assert info.file_count == 15
    assert info.chunk_count == 140
    assert info.languages == {"typescript": 14, "javascript": 1}
