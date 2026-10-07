"""Tests for Document-page slugging, mention extraction, validation, and
Neo4j/Qdrant IO (stores mocked — no DB/network)."""

from unittest.mock import MagicMock

from code_vector_graph.ingestion.okf.features.documents import (
    build_document_chunks,
    build_document_graph,
    document_id_for,
    extract_mentioned_paths,
    resolve_mentions,
    slugify,
    sync_document_neo4j,
    sync_document_qdrant,
    unique_slug,
    word_count,
)
from code_vector_graph.ingestion.okf.features.models import DocumentFrontmatter, DocumentPage
from code_vector_graph.ingestion.okf.features.template import first_paragraph
from code_vector_graph.ingestion.okf.features.validate import validate_document_body
from code_vector_graph.stores.graph_schema import validate_node


def _page(**overrides) -> DocumentPage:
    fm_kwargs = dict(
        title="Deploy Runbook", slug="deploy-runbook", description="How to deploy.",
        app="demo", repo="demo-repo", doc_id="doc-1", category="runbook",
        created_at="2026-08-29T00:00:00Z",
    )
    fm_kwargs.update(overrides)
    body = "# Deploy Runbook\n\nRun `scripts/deploy.sh` after tests pass.\n"
    return DocumentPage(fm=DocumentFrontmatter(**fm_kwargs), body=body)


# --- slugify / unique_slug / document_id_for ------------------------------


def test_slugify_lowercases_and_replaces_punctuation():
    assert slugify("Deploy Runbook v2!") == "deploy-runbook-v2"


def test_slugify_unicode_and_empty_fallback():
    assert slugify("日本語") == "document"
    assert slugify("") == "document"
    assert slugify("   ") == "document"


def test_slugify_respects_max_len():
    long_title = "a " * 60
    slug = slugify(long_title, max_len=20)
    assert len(slug) <= 20
    assert not slug.startswith("-") and not slug.endswith("-")


def test_unique_slug_appends_incrementing_suffix():
    taken = {"deploy-runbook", "deploy-runbook-2"}
    assert unique_slug("deploy-runbook", taken) == "deploy-runbook-3"
    assert unique_slug("fresh-slug", taken) == "fresh-slug"


def test_document_id_for_is_stable_and_scoped_by_repo_and_none():
    a = document_id_for("demo", "repo-a", "runbook")
    b = document_id_for("demo", "repo-b", "runbook")
    c = document_id_for("demo", None, "runbook")
    assert document_id_for("demo", "repo-a", "runbook") == a
    assert len({a, b, c}) == 3


# --- extract_mentioned_paths -----------------------------------------------


def test_extract_mentioned_paths_from_backticks_and_links():
    body = (
        "# Doc\n\nSee `src/api/app.py` and [the client](frontend/src/lib/api/client.ts).\n"
    )
    assert extract_mentioned_paths(body) == ["src/api/app.py", "frontend/src/lib/api/client.ts"]


def test_extract_mentioned_paths_strips_location_suffixes_and_dot_slash():
    body = "See `./src/app.py:42` and `src/other.py#L10-L20`.\n"
    assert extract_mentioned_paths(body) == ["src/app.py", "src/other.py"]


def test_extract_mentioned_paths_skips_urls_and_non_path_tokens():
    body = "Visit `https://example.com` or email `mailto:a@b.com`. Also `just_a_word`.\n"
    assert extract_mentioned_paths(body) == []


def test_extract_mentioned_paths_ignores_fenced_code():
    body = "```\n`src/inside/fence.py`\n```\n\n`src/outside/fence.py`\n"
    assert extract_mentioned_paths(body) == ["src/outside/fence.py"]


def test_extract_mentioned_paths_dedupes_and_caps():
    body = "\n".join(f"`file_{i}.py`" for i in range(250))
    result = extract_mentioned_paths(body)
    assert len(result) == 200


def test_extract_mentioned_paths_requires_slash_or_code_extension():
    body = "`README.md` and `random-token` and `nested/dir`.\n"
    assert extract_mentioned_paths(body) == ["README.md", "nested/dir"]


# --- validate_document_body -------------------------------------------------


def test_validate_document_body_requires_h1():
    result = validate_document_body("Just some text, no heading.\n")
    assert not result.ok
    assert any(e.code == "missing_h1" for e in result.errors)


def test_validate_document_body_allows_free_h2_and_multiple_mermaid():
    body = (
        "# Doc\n\n## Whatever\n\ntext\n\n"
        "```mermaid\nflowchart TD; A-->B\n```\n\n"
        "```mermaid\nflowchart TD; C-->D\n```\n"
    )
    result = validate_document_body(body)
    assert result.ok


def test_validate_document_body_setext_is_warning_not_error():
    body = "# Doc\n\nSubtitle\n--------\n\nBody text.\n"
    result = validate_document_body(body)
    assert result.ok
    assert any(w.code == "setext_heading" for w in result.warnings)


def test_validate_document_body_relative_link_is_warning():
    body = "# Doc\n\nSee [other](../other.md) for more.\n"
    result = validate_document_body(body)
    assert result.ok
    assert any(w.code == "bad_link" for w in result.warnings)


def test_validate_document_body_raw_html_is_error():
    body = "# Doc\n\n<script>alert(1)</script>\n"
    result = validate_document_body(body)
    assert not result.ok
    assert any(e.code == "raw_html" for e in result.errors)


def test_validate_document_body_unclosed_fence_is_error():
    body = "# Doc\n\n```\nno closing fence\n"
    result = validate_document_body(body)
    assert not result.ok
    assert any(e.code == "unclosed_fence" for e in result.errors)


def test_validate_document_body_over_max_chars_is_error():
    body = "# Doc\n\n" + ("x" * 200_050)
    result = validate_document_body(body)
    assert not result.ok
    assert any(e.code == "too_long" for e in result.errors)


def test_validate_document_body_title_only_warns_empty():
    result = validate_document_body("# Doc\n")
    assert result.ok
    assert any(w.code == "empty_body" for w in result.warnings)


# --- first_paragraph ---------------------------------------------------------


def test_first_paragraph_skips_heading_and_fence():
    body = "# Title\n\n## Section\n\n```\ncode here\n```\n\nActual first paragraph text.\n\nMore.\n"
    assert first_paragraph(body) == "Actual first paragraph text."


def test_first_paragraph_truncates_with_ellipsis():
    text = "word " * 100
    result = first_paragraph(f"# T\n\n{text}", max_chars=20)
    assert len(result) <= 20
    assert result.endswith("…")


# --- build_document_graph ----------------------------------------------------


def test_build_document_graph_produces_valid_wikipage_node():
    page = _page()
    nodes, rels, node_labels = build_document_graph(page, [], target_id="repo-id-1", target_label="Repository")
    assert len(nodes) == 1
    assert validate_node("WikiPage", nodes[0]["properties"])
    assert nodes[0]["properties"]["type"] == "Document"
    assert node_labels[nodes[0]["id"]] == "WikiPage"


def test_build_document_graph_documents_edge_points_at_repository():
    page = _page()
    nodes, rels, _ = build_document_graph(page, [], target_id="repo-id-1", target_label="Repository")
    wid = nodes[0]["id"]
    documents = [r for r in rels if r["type"] == "DOCUMENTS"]
    assert documents == [{"type": "DOCUMENTS", "source_id": wid, "target_id": "repo-id-1", "properties": {}}]


def test_build_document_graph_documents_edge_points_at_application_when_no_repo():
    page = _page(repo=None)
    nodes, rels, node_labels = build_document_graph(page, [], target_id="app-id-1", target_label="Application")
    documents = [r for r in rels if r["type"] == "DOCUMENTS"]
    assert documents[0]["target_id"] == "app-id-1"
    assert node_labels["app-id-1"] == "Application"


def test_build_document_graph_mentions_edges_carry_token_path():
    page = _page()
    mentions = [{"id": "file-1", "path": "/root/src/app.py", "rel_path": "src/app.py", "repo": "demo-repo", "token": "src/app.py"}]
    nodes, rels, node_labels = build_document_graph(page, mentions, target_id="repo-id-1", target_label="Repository")
    mention_rels = [r for r in rels if r["type"] == "MENTIONS"]
    assert mention_rels == [
        {"type": "MENTIONS", "source_id": nodes[0]["id"], "target_id": "file-1", "properties": {"path": "src/app.py"}}
    ]
    assert node_labels["file-1"] == "File"
    assert nodes[0]["properties"]["mentions"] == ["src/app.py"]


# --- sync_document_neo4j ------------------------------------------------------


def test_sync_document_neo4j_deletes_old_mentions_before_upsert():
    graph = MagicMock()
    page = _page()
    sync_document_neo4j(page, [], target_id="repo-id-1", target_label="Repository", graph_store=graph)

    graph.create_constraints.assert_called_once()
    delete_call = graph.query_graph.call_args_list[0]
    assert "DELETE r" in delete_call.args[0]
    graph.upsert_nodes.assert_called_once()
    graph.upsert_relationships.assert_called_once()


# --- resolve_mentions ---------------------------------------------------------


def test_resolve_mentions_returns_empty_without_query_for_no_tokens():
    graph = MagicMock()
    scope = MagicMock()
    assert resolve_mentions(graph, scope, []) == []
    graph.query_graph.assert_not_called()


def test_resolve_mentions_maps_records_to_dicts():
    graph = MagicMock()
    scope = MagicMock()
    scope.cypher_file_where.return_value = ("true", {})
    graph.query_graph.return_value.records = [
        {"id": "file-1", "path": "/root/src/app.py", "rel_path": "src/app.py", "repo": "demo-repo", "token": "src/app.py"}
    ]
    result = resolve_mentions(graph, scope, ["src/app.py"])
    assert result == [{"id": "file-1", "path": "/root/src/app.py", "rel_path": "src/app.py", "repo": "demo-repo", "token": "src/app.py"}]


# --- build_document_chunks / sync_document_qdrant -----------------------------


def test_build_document_chunks_tags_source_kind_symbol_id():
    page = _page()
    chunks = build_document_chunks(page, tokenizer_name="bert-base-uncased")
    assert chunks
    for ch in chunks:
        assert ch["source"] == "okf_wiki"
        assert ch["kind"] == "Document"
        assert ch["symbol_id"] == "doc-1"
        assert ch["app"] == "demo"
        assert ch["repo"] == "demo-repo"


def test_sync_document_qdrant_deletes_before_embedding_and_reports_progress():
    page = _page()
    vector_store = MagicMock()
    vector_store.upsert_chunks.side_effect = lambda chunks: [c["id"] for c in chunks]
    embedder = MagicMock()
    embedder.embed_chunks.side_effect = lambda chunks, batch_size=16: chunks
    progress: list[tuple[int, int]] = []

    stats = sync_document_qdrant(
        page, embedder, vector_store, tokenizer_name="bert-base-uncased",
        batch_size=1, report=lambda done, total: progress.append((done, total)),
    )

    vector_store.delete_by_symbol_id.assert_called_once_with("doc-1")
    assert stats["chunks"] >= 1
    assert progress
    assert all(a <= b for a, b in zip([p[0] for p in progress], [p[0] for p in progress][1:]))
    assert progress[-1][0] == progress[-1][1]


# --- word_count ---------------------------------------------------------------


def test_word_count_counts_whitespace_separated_tokens():
    assert word_count("one two   three\nfour") == 4
    assert word_count("") == 0
