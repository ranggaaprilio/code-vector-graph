"""Tests for the /api/apps/{app}/docs* feature-doc endpoints.

Neo4j is faked with the ordered-script `FakeGraph` from conftest.py (each
endpoint issues a small, predictable sequence of queries); Qdrant/embedder/
LLM are mocked. `DocsJobManager` is also unit-tested directly (no HTTP).
"""

import json
import time
from unittest.mock import MagicMock

import pytest

pytest.importorskip("fastapi")

from fastapi.testclient import TestClient  # noqa: E402

from code_vector_graph.api.app import app as fastapi_app  # noqa: E402
from code_vector_graph.api.deps import (  # noqa: E402
    get_docs_jobs,
    get_embedder,
    get_graph,
    get_llm_client,
    get_qdrant,
    get_registry,
    get_vector_store,
)
from code_vector_graph.api.services.docs_jobs import DocsJobManager  # noqa: E402
from code_vector_graph.ingestion.okf.features.models import EntryPoint, FeatureDoc  # noqa: E402
from code_vector_graph.ingestion.okf.features.template import render_feature_markdown  # noqa: E402

from .conftest import FakeGraph, FakeNode, StubRegistry, make_repo  # noqa: E402

FEATURE_ID = "feat-user-login"
WIKI_ID = "wid-user-login"

VALID_BODY = render_feature_markdown(
    "User Login",
    FeatureDoc(
        title="User Login", description="Handles login.", overview="Lets users authenticate.",
        business_rules=["Password must match."], process_flow=["Submit.", "Verify."],
        entry_points=[EntryPoint(kind="Function", name="login", file="auth/login.js", line=1)],
    ),
)


def _feature_node(**overrides) -> FakeNode:
    props = {
        "id": WIKI_ID, "concept_id": FEATURE_ID, "type": "Feature", "slug": "user-login",
        "title": "User Login", "summary": "Handles login.", "overview": "Lets users authenticate.",
        "content": VALID_BODY, "kind": "user-facing", "source": "llm", "stale": False,
        "stale_since": None, "app": "onebid", "repo": "backend_nodejs_global_tnlm",
        "member_files": ["auth/login.js"], "member_count": 1, "tags": ["auth"],
        "generated_at": "2026-01-01T00:00:00Z", "edited_at": None, "edited_members_hash": None,
        "members_hash": "abc1234567890def", "model": "deepseek-v4-pro", "language": "en",
        "needs_reembed": False, "draft": None, "draft_generated_at": None,
    }
    props.update(overrides)
    return FakeNode(props, labels=["WikiPage"])


@pytest.fixture
def docs_registry():
    return StubRegistry(apps=None)  # onebid, two repos — see conftest.ONEBID_ROOTS


@pytest.fixture
def docs_client(docs_registry):
    graph = FakeGraph()
    vector_store = MagicMock()
    vector_store.upsert_chunks.return_value = ["p1"]
    embedder = MagicMock()
    embedder.embed_chunks.side_effect = lambda chunks, batch_size=64: chunks
    llm_client = MagicMock()
    jobs = DocsJobManager()

    fastapi_app.dependency_overrides[get_graph] = lambda: graph
    fastapi_app.dependency_overrides[get_qdrant] = lambda: MagicMock()
    fastapi_app.dependency_overrides[get_registry] = lambda: docs_registry
    fastapi_app.dependency_overrides[get_vector_store] = lambda: vector_store
    fastapi_app.dependency_overrides[get_embedder] = lambda: embedder
    fastapi_app.dependency_overrides[get_llm_client] = lambda: llm_client
    fastapi_app.dependency_overrides[get_docs_jobs] = lambda: jobs
    try:
        yield TestClient(fastapi_app), graph, vector_store, embedder, llm_client, jobs
    finally:
        fastapi_app.dependency_overrides.clear()


# --- list ---------------------------------------------------------------


def test_list_docs_returns_features(docs_client):
    client, graph, *_ = docs_client
    graph.queue([{"n": 1}])  # count
    graph.queue([{
        "feature_id": FEATURE_ID, "slug": "user-login", "title": "User Login", "summary": "Handles login.",
        "kind": "user-facing", "repo": "backend_nodejs_global_tnlm", "source": "llm", "stale": False,
        "member_files": ["auth/login.js"], "tags": ["auth"], "generated_at": "t", "edited_at": None,
        "needs_reembed": False,
    }])
    res = client.get("/api/apps/onebid/docs")
    assert res.status_code == 200
    body = res.json()
    assert body["total"] == 1
    assert body["features"][0]["slug"] == "user-login"
    assert body["features"][0]["member_count"] == 1


# --- detail ---------------------------------------------------------------


def test_get_doc_returns_page_and_members(docs_client):
    client, graph, *_ = docs_client
    graph.queue([{"w": _feature_node()}])
    graph.queue([{"id": "fnid-1", "label": "Function", "role": "entry_point",
                  "name": "login", "file_path": "auth/login.js", "start_line": 1}])
    res = client.get(f"/api/apps/onebid/docs/{FEATURE_ID}")
    assert res.status_code == 200
    body = res.json()
    assert body["page"]["slug"] == "user-login"
    assert body["members"][0]["role"] == "entry_point"
    assert body["repo_root_accessible"] is False  # ONEBID_ROOTS paths don't exist on this machine


def test_get_doc_404_when_missing(docs_client):
    client, graph, *_ = docs_client
    graph.queue([])
    res = client.get("/api/apps/onebid/docs/does-not-exist")
    assert res.status_code == 404


# --- validate ---------------------------------------------------------------


def test_validate_doc_endpoint_valid(docs_client):
    client, *_ = docs_client
    res = client.post("/api/apps/onebid/docs/validate", json={"markdown": VALID_BODY, "title": "User Login"})
    assert res.status_code == 200
    assert res.json()["ok"] is True


def test_validate_doc_endpoint_invalid(docs_client):
    client, *_ = docs_client
    res = client.post("/api/apps/onebid/docs/validate", json={"markdown": "# Just a title\n", "title": "Just a title"})
    assert res.status_code == 200
    body = res.json()
    assert body["ok"] is False
    assert body["errors"]


# --- update (PUT) ---------------------------------------------------------------


def test_update_doc_valid_saves_and_reembeds(docs_client):
    client, graph, vector_store, embedder, *_ = docs_client
    graph.queue([{"w": _feature_node()}])  # _fetch_feature
    graph.queue([{"w": _feature_node(content=VALID_BODY, source="human")}])  # save_feature_page RETURN w
    res = client.put(f"/api/apps/onebid/docs/{FEATURE_ID}", json={"markdown": VALID_BODY})
    assert res.status_code == 200
    body = res.json()
    assert body["validation"]["ok"] is True
    assert body["reembedded"] is True
    vector_store.delete_by_symbol_id.assert_called_once_with(FEATURE_ID)
    embedder.embed_chunks.assert_called_once()


def test_update_doc_invalid_returns_422(docs_client):
    client, graph, *_ = docs_client
    graph.queue([{"w": _feature_node()}])
    res = client.put(f"/api/apps/onebid/docs/{FEATURE_ID}", json={"markdown": "# Just a title\n"})
    assert res.status_code == 422
    assert res.json()["detail"]["validation"]["ok"] is False


def test_update_doc_non_feature_returns_400(docs_client):
    client, graph, *_ = docs_client
    graph.queue([{"w": _feature_node(type="File")}])
    res = client.put(f"/api/apps/onebid/docs/{FEATURE_ID}", json={"markdown": VALID_BODY})
    assert res.status_code == 400


def test_update_doc_missing_returns_404(docs_client):
    client, graph, *_ = docs_client
    graph.queue([])
    res = client.put("/api/apps/onebid/docs/nope", json={"markdown": VALID_BODY})
    assert res.status_code == 404


def test_update_doc_stale_expected_edited_at_returns_409(docs_client):
    client, graph, *_ = docs_client
    graph.queue([{"w": _feature_node(edited_at="2026-01-01T00:00:00Z")}])
    res = client.put(
        f"/api/apps/onebid/docs/{FEATURE_ID}",
        json={"markdown": VALID_BODY, "expected_edited_at": "2025-12-31T00:00:00Z"},
    )
    assert res.status_code == 409


def test_update_doc_marks_needs_reembed_when_embedder_unavailable(docs_client):
    client, graph, vector_store, *_ = docs_client
    fastapi_app.dependency_overrides[get_embedder] = lambda: None
    graph.queue([{"w": _feature_node()}])
    graph.queue([{"w": _feature_node(content=VALID_BODY, needs_reembed=True)}])
    res = client.put(f"/api/apps/onebid/docs/{FEATURE_ID}", json={"markdown": VALID_BODY})
    assert res.status_code == 200
    body = res.json()
    assert body["reembedded"] is False
    assert body["page"]["needs_reembed"] is True
    # save_feature_page was called with needs_reembed=True — verify via the params on the 2nd query
    cypher, params = graph.calls[1]
    assert params["needs_reembed"] is True


# --- regenerate ---------------------------------------------------------------


def test_regenerate_doc_graph_only_when_repo_not_accessible(docs_client):
    client, graph, _vs, _emb, llm_client, _jobs = docs_client
    llm_client.chat.completions.create.return_value = MagicMock(
        choices=[MagicMock(message=MagicMock(content=json.dumps({
            "title": "User Login", "description": "d", "overview": "o",
            "business_rules": ["r"], "process_flow": ["a", "b"],
        })))]
    )
    graph.queue([{"w": _feature_node()}])  # _fetch_feature
    res = client.post(f"/api/apps/onebid/docs/{FEATURE_ID}/regenerate")
    assert res.status_code == 200
    body = res.json()
    assert body["grounding"] == "graph-only"
    assert body["validation"]["ok"] is True


def test_regenerate_doc_503_without_llm_client(docs_client):
    client, graph, *_ = docs_client
    fastapi_app.dependency_overrides[get_llm_client] = lambda: None
    graph.queue([{"w": _feature_node()}])
    res = client.post(f"/api/apps/onebid/docs/{FEATURE_ID}/regenerate")
    assert res.status_code == 503


def test_regenerate_doc_save_draft_writes_to_graph(docs_client):
    client, graph, _vs, _emb, llm_client, _jobs = docs_client
    llm_client.chat.completions.create.return_value = MagicMock(
        choices=[MagicMock(message=MagicMock(content=json.dumps({
            "title": "User Login", "overview": "o", "business_rules": ["r"], "process_flow": ["a", "b"],
        })))]
    )
    graph.queue([{"w": _feature_node()}])
    res = client.post(f"/api/apps/onebid/docs/{FEATURE_ID}/regenerate?save_draft=true")
    assert res.status_code == 200
    assert "SET w.draft" in graph.last_cypher


# --- generate (job trigger) ---------------------------------------------------------------


def test_generate_docs_409_when_repo_not_accessible(docs_client):
    client, *_ = docs_client
    res = client.post("/api/apps/onebid/docs/generate", json={})
    assert res.status_code == 409
    assert res.json()["detail"]["error"] == "repo_not_accessible"


def test_generate_docs_409_when_already_running(docs_client, docs_registry):
    client, _graph, _vs, _emb, _llm, jobs = docs_client
    accessible_repo = make_repo("acc-repo", app="onebid", root="/", source="recorded")
    fastapi_app.dependency_overrides[get_registry] = lambda: StubRegistry(
        apps=[type(docs_registry.apps[0]).aggregate("onebid", [accessible_repo])]
    )

    import threading
    gate = threading.Event()
    started = threading.Event()

    def _slow():
        started.set()
        gate.wait(timeout=2)
        return {}

    jobs.start("onebid", None, _slow)  # occupy the slot until we release the gate
    assert started.wait(timeout=1), "occupying job never started"
    try:
        res = client.post("/api/apps/onebid/docs/generate", json={})
        assert res.status_code == 409
        assert "already running" in res.json()["detail"]
    finally:
        gate.set()


# --- Document create/get/update/reindex/delete ------------------------------


def _wait(jobs, job_id, timeout=2.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        job = jobs.get(job_id)
        if job.status in ("done", "failed"):
            return job
        time.sleep(0.01)
    raise AssertionError(f"job {job_id} did not finish in time")


DOCUMENT_BODY = "# Deploy Runbook\n\nRun the deploy script after tests pass.\n"


def test_create_document_indexes_and_links_to_repository(docs_client):
    client, graph, vector_store, embedder, *_ = docs_client
    res = client.post("/api/apps/onebid/docs", json={"markdown": DOCUMENT_BODY, "repo": "backend_nodejs_global_tnlm"})
    assert res.status_code == 202
    body = res.json()
    job = _wait(docs_client[-1], body["job_id"])
    assert job.status == "done"

    assert len(graph.upserted_nodes) == 1
    node = graph.upserted_nodes[0][0]
    assert node["properties"]["type"] == "Document"
    assert node["properties"]["title"] == "Deploy Runbook"
    from code_vector_graph.repos import RepoIdentity

    documents_rel = next(r for r in graph.upserted_rels[0] if r["type"] == "DOCUMENTS")
    assert documents_rel["target_id"] == RepoIdentity(app="onebid", name="backend_nodejs_global_tnlm", root="/x").id
    vector_store.delete_by_symbol_id.assert_called_once_with(body["doc_id"])
    embedder.embed_chunks.assert_called()


def test_create_document_app_level_links_to_application(docs_client):
    client, graph, *_ = docs_client
    res = client.post("/api/apps/onebid/docs", json={"markdown": DOCUMENT_BODY})
    assert res.status_code == 202
    body = res.json()
    _wait(docs_client[-1], body["job_id"])

    from code_vector_graph.repos import RepoIdentity

    documents_rel = next(r for r in graph.upserted_rels[0] if r["type"] == "DOCUMENTS")
    assert documents_rel["target_id"] == RepoIdentity(app="onebid", name="", root="").app_id


def test_create_document_missing_h1_returns_422(docs_client):
    client, *_ = docs_client
    res = client.post("/api/apps/onebid/docs", json={"markdown": "Just some text, no heading.\n"})
    assert res.status_code == 422
    assert res.json()["detail"]["validation"]["ok"] is False


def test_create_document_raw_html_returns_422(docs_client):
    client, *_ = docs_client
    res = client.post("/api/apps/onebid/docs", json={"markdown": "# Doc\n\n<script>1</script>\n"})
    assert res.status_code == 422


def test_create_document_title_only_prepends_h1(docs_client):
    client, graph, *_ = docs_client
    res = client.post("/api/apps/onebid/docs", json={"markdown": "Body with no heading.\n", "title": "My Note"})
    assert res.status_code == 202
    body = res.json()
    _wait(docs_client[-1], body["job_id"])
    assert body["slug"] == "my-note"
    node = graph.upserted_nodes[0][0]
    assert node["properties"]["title"] == "My Note"
    assert node["properties"]["content"].startswith("# My Note\n")


def test_create_document_slug_collision_appends_suffix(docs_client):
    client, graph, *_ = docs_client
    graph.queue([{"slug": "deploy-runbook"}, {"slug": "deploy-runbook-2"}])
    res = client.post("/api/apps/onebid/docs", json={"markdown": DOCUMENT_BODY})
    assert res.status_code == 202
    assert res.json()["slug"] == "deploy-runbook-3"


def test_create_document_without_embedder_marks_needs_reembed(docs_client):
    client, graph, vector_store, *_ = docs_client
    fastapi_app.dependency_overrides[get_embedder] = lambda: None
    res = client.post("/api/apps/onebid/docs", json={"markdown": DOCUMENT_BODY})
    assert res.status_code == 202
    body = res.json()
    job = _wait(docs_client[-1], body["job_id"])
    assert job.status == "done"
    assert job.result["needs_reembed"] is True
    vector_store.upsert_chunks.assert_not_called()
    node = graph.upserted_nodes[0][0]
    assert node["properties"]["needs_reembed"] is True


def test_create_document_409_when_already_indexing(docs_client):
    client, graph, *_ = docs_client
    jobs = docs_client[-1]

    import threading
    gate = threading.Event()
    started = threading.Event()

    def _slow(report):
        started.set()
        gate.wait(timeout=2)
        return {}

    from code_vector_graph.ingestion.okf.features.documents import document_id_for

    doc_id = document_id_for("onebid", None, "deploy-runbook")
    jobs.start("onebid", None, _slow, kind="index_document", key=doc_id)
    assert started.wait(timeout=1)
    try:
        res = client.post("/api/apps/onebid/docs", json={"markdown": DOCUMENT_BODY})
        assert res.status_code == 409
    finally:
        gate.set()


def _document_node(**overrides) -> FakeNode:
    props = {
        "id": "wid-doc-1", "concept_id": "doc-1", "type": "Document", "slug": "deploy-runbook",
        "title": "Deploy Runbook", "summary": "How to deploy.", "content": DOCUMENT_BODY,
        "category": "runbook", "source": "human", "app": "onebid", "repo": "backend_nodejs_global_tnlm",
        "tags": ["ops"], "created_at": "2026-08-29T00:00:00Z", "edited_at": None,
        "needs_reembed": False, "word_count": 8, "mentions": [], "member_files": [],
    }
    props.update(overrides)
    return FakeNode(props, labels=["WikiPage"])


def test_get_document_returns_mentions_and_indexing_job(docs_client):
    client, graph, *_ = docs_client
    graph.queue([{"w": _document_node()}])
    graph.queue([{"id": "file-1", "path": "/root/src/app.py", "rel_path": "src/app.py", "repo": "backend_nodejs_global_tnlm", "token": "src/app.py"}])
    res = client.get("/api/apps/onebid/docs/doc-1")
    assert res.status_code == 200
    body = res.json()
    assert body["page"]["type"] == "Document"
    assert body["mentions"][0]["token"] == "src/app.py"
    assert body["members"] == []
    assert body["indexing_job"] is None


def test_list_docs_type_filter_document(docs_client):
    client, graph, *_ = docs_client
    graph.queue([{"n": 1}])
    graph.queue([{
        "feature_id": "doc-1", "slug": "deploy-runbook", "title": "Deploy Runbook", "summary": "s",
        "type": "Document", "kind": None, "category": "runbook", "repo": "backend_nodejs_global_tnlm",
        "source": "human", "stale": False, "member_files": [], "mention_count": 1, "word_count": 8,
        "tags": ["ops"], "generated_at": None, "created_at": "t", "edited_at": None, "needs_reembed": False,
    }])
    res = client.get("/api/apps/onebid/docs", params={"type": "Document"})
    assert res.status_code == 200
    body = res.json()
    assert body["features"][0]["type"] == "Document"
    assert body["features"][0]["category"] == "runbook"
    _, params = graph.calls[-1]
    assert params["type"] == "Document"


def test_update_document_relaxed_validation_starts_reindex_job(docs_client):
    client, graph, vector_store, embedder, *_ = docs_client
    graph.queue([{"w": _document_node()}])  # _fetch_page
    graph.queue([{"w": _document_node(content="# Deploy Runbook\n\nUpdated body.\n")}])  # save_document_page RETURN w
    res = client.put("/api/apps/onebid/docs/doc-1", json={"markdown": "# Deploy Runbook\n\nUpdated body.\n"})
    assert res.status_code == 200
    body = res.json()
    assert body["validation"]["ok"] is True
    assert "job_id" in body
    job = _wait(docs_client[-1], body["job_id"])
    assert job.status == "done"


def test_update_document_stale_expected_edited_at_returns_409(docs_client):
    client, graph, *_ = docs_client
    graph.queue([{"w": _document_node(edited_at="2026-01-01T00:00:00Z")}])
    res = client.put(
        "/api/apps/onebid/docs/doc-1",
        json={"markdown": DOCUMENT_BODY, "expected_edited_at": "2025-12-31T00:00:00Z"},
    )
    assert res.status_code == 409


def test_reindex_doc_succeeds_then_409_while_a_second_run_is_in_flight(docs_client):
    client, graph, *_ = docs_client
    jobs = docs_client[-1]

    graph.queue([{"w": _document_node()}])
    res = client.post("/api/apps/onebid/docs/doc-1/reindex")
    assert res.status_code == 202
    _wait(jobs, res.json()["job_id"])

    import threading
    gate = threading.Event()
    started = threading.Event()

    def _slow(report):
        started.set()
        gate.wait(timeout=2)
        return {}

    jobs.start("onebid", None, _slow, kind="index_document", key="doc-1")
    assert started.wait(timeout=1)
    try:
        graph.queue([{"w": _document_node()}])
        res2 = client.post("/api/apps/onebid/docs/doc-1/reindex")
        assert res2.status_code == 409
    finally:
        gate.set()


def test_delete_document_removes_from_both_stores(docs_client):
    client, graph, vector_store, *_ = docs_client
    graph.queue([{"w": _document_node()}])
    res = client.delete("/api/apps/onebid/docs/doc-1")
    assert res.status_code == 200
    assert res.json()["deleted"] is True
    vector_store.delete_by_symbol_id.assert_called_once_with("doc-1")
    assert "DETACH DELETE w" in graph.last_cypher


def test_delete_feature_returns_400(docs_client):
    client, graph, *_ = docs_client
    graph.queue([{"w": _feature_node()}])
    res = client.delete(f"/api/apps/onebid/docs/{FEATURE_ID}")
    assert res.status_code == 400


def test_validate_doc_endpoint_document_type(docs_client):
    client, *_ = docs_client
    res = client.post("/api/apps/onebid/docs/validate", json={"markdown": DOCUMENT_BODY, "type": "Document"})
    assert res.status_code == 200
    assert res.json()["ok"] is True


# --- DocsJobManager (unit, no HTTP) ------------------------------------------


def test_docs_job_manager_tracks_success():
    jobs = DocsJobManager()
    job_id = jobs.start("app1", None, lambda: {"ok": True})
    for _ in range(50):
        job = jobs.get(job_id)
        if job.status == "done":
            break
        time.sleep(0.02)
    assert job.status == "done"
    assert job.result == {"ok": True}
    assert jobs.latest("app1").job_id == job_id


def test_docs_job_manager_tracks_failure():
    jobs = DocsJobManager()

    def _boom():
        raise RuntimeError("kaboom")

    job_id = jobs.start("app1", None, _boom)
    for _ in range(50):
        job = jobs.get(job_id)
        if job.status == "failed":
            break
        time.sleep(0.02)
    assert job.status == "failed"
    assert "kaboom" in job.error


def test_docs_job_manager_is_running_true_while_in_flight():
    jobs = DocsJobManager()
    started = MagicMock()

    import threading
    gate = threading.Event()

    def _slow():
        started.set()
        gate.wait(timeout=1)
        return {}

    jobs.start("app1", None, _slow)
    started_flag = False
    for _ in range(50):
        if jobs.is_running("app1"):
            started_flag = True
            break
        time.sleep(0.01)
    assert started_flag
    gate.set()


def test_docs_job_manager_per_kind_and_key_lock_is_independent():
    jobs = DocsJobManager()
    import threading
    gate = threading.Event()
    started = threading.Event()

    def _slow(report):
        started.set()
        report("embedding", done=0, total=1)
        gate.wait(timeout=2)
        return {}

    jobs.start("app1", None, _slow, kind="index_document", key="doc-1", stages=("embedding", "done"))
    assert started.wait(timeout=1)
    try:
        # Locked for this doc + kind...
        assert jobs.is_running("app1", "index_document", key="doc-1")
        # ...but not for a different document, and not for "generate".
        assert not jobs.is_running("app1", "index_document", key="doc-2")
        assert not jobs.is_running("app1", "generate")
    finally:
        gate.set()


def test_docs_job_manager_report_updates_stage_and_progress():
    jobs = DocsJobManager()

    def _run(report):
        report("saving_graph")
        report("embedding", done=1, total=3, message="1/3 chunks")
        return {"chunks": 3}

    job_id = jobs.start(
        "app1", None, _run, kind="index_document", key="doc-1",
        stages=("saving_graph", "embedding", "done"), target={"doc_id": "doc-1", "slug": "s", "title": "T"},
    )
    for _ in range(50):
        job = jobs.get(job_id)
        if job.status == "done":
            break
        time.sleep(0.02)
    assert job.status == "done"
    assert job.stage == "done"  # advances to the last declared stage on success
    assert job.progress == {"done": 1, "total": 3}
    assert job.message == "1/3 chunks"
    assert job.target == {"doc_id": "doc-1", "slug": "s", "title": "T"}
    assert job.kind == "index_document"


def test_docs_job_manager_zero_arg_fn_still_supported():
    jobs = DocsJobManager()
    job_id = jobs.start("app1", None, lambda: {"ok": True}, kind="index_document", key="doc-1")
    for _ in range(50):
        job = jobs.get(job_id)
        if job.status == "done":
            break
        time.sleep(0.02)
    assert job.status == "done"
    assert job.result == {"ok": True}


def test_docs_job_manager_latest_for_is_independent_of_latest_generate():
    jobs = DocsJobManager()
    gen_id = jobs.start("app1", None, lambda: {"a": 1})
    doc_id = jobs.start("app1", None, lambda: {"b": 2}, kind="index_document", key="doc-1")
    for jid in (gen_id, doc_id):
        for _ in range(50):
            if jobs.get(jid).status == "done":
                break
            time.sleep(0.01)
    assert jobs.latest("app1").job_id == gen_id
    assert jobs.latest_for("app1", "index_document", key="doc-1").job_id == doc_id
