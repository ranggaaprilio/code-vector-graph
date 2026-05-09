import pytest
from unittest.mock import MagicMock

try:
    from src.hybrid_retriever import reciprocal_rank_fusion, HybridRetriever
except Exception:
    reciprocal_rank_fusion = None
    HybridRetriever = None

@pytest.mark.skipif(reciprocal_rank_fusion is None, reason="hybrid_retriever not implemented")
def test_rrf_two_lists():
    ranked_lists = [
        [("a", 0.9), ("b", 0.8)],
        [("b", 0.85), ("c", 0.7)],
    ]
    result = reciprocal_rank_fusion(ranked_lists, k=60, weights=[0.7, 0.3])
    assert result[0][0] == "b"
    assert isinstance(result[0][1], float)

@pytest.mark.skipif(reciprocal_rank_fusion is None, reason="hybrid_retriever not implemented")
def test_rrf_overlapping_docs_combined():
    ranked_lists = [
        [("x", 1.0), ("y", 0.6)],
        [("x", 0.9), ("z", 0.5)],
    ]
    results = reciprocal_rank_fusion(ranked_lists, k=60, weights=[0.6, 0.4])
    docs = [doc for doc, _ in results]
    assert "x" in docs

@pytest.mark.skipif(reciprocal_rank_fusion is None, reason="hybrid_retriever not implemented")
def test_rrf_single_list():
    ranked_lists = [
        [("d1", 0.95), ("d2", 0.4)],
    ]
    results = reciprocal_rank_fusion(ranked_lists, k=60)
    assert results[0][0] == "d1"

@pytest.mark.skipif(reciprocal_rank_fusion is None, reason="hybrid_retriever not implemented")
def test_rrf_no_overlap_combined_scores_sorted():
    ranked_lists = [
        [("a", 0.9)],
        [("b", 0.8)],
    ]
    results = reciprocal_rank_fusion(ranked_lists, k=60, weights=[0.6, 0.4])
    assert results[0][0] in ("a", "b")

@pytest.mark.skipif(reciprocal_rank_fusion is None, reason="hybrid_retriever not implemented")
def test_rrf_empty_lists_returns_empty():
    results = reciprocal_rank_fusion([[], []], k=60)
    assert results == []

@pytest.mark.skipif(HybridRetriever is None, reason="hybrid_retriever not implemented")
def test_hybrid_search_vector_mode_calls_vector_only():
    vector_store = MagicMock()
    graph_store = MagicMock()
    embedder = MagicMock()
    vector_store.search.return_value = [
        {"id": "doc1", "payload": {"file_path": "test.ts"}, "score": 0.9},
    ]
    retriever = HybridRetriever(vector_store=vector_store, graph_store=graph_store, embedder=embedder)
    results = retriever.search("query", mode="vector", top_k=5)
    vector_store.search.assert_called_once()
    # graph_store.query_graph should NOT be called in vector mode
    graph_store.query_graph.assert_not_called()

@pytest.mark.skipif(HybridRetriever is None, reason="hybrid_retriever not implemented")
def test_hybrid_search_calls_both_stores_and_merges():
    vector_store = MagicMock()
    graph_store = MagicMock()
    embedder = MagicMock()
    vector_store.search.return_value = [
        {"id": "doc1", "payload": {"file_path": "test.ts"}, "score": 0.9},
    ]
    graph_store.query_graph.return_value = [
        {"id": "doc2", "node": {"name": "test_func"}, "score": 1.0},
    ]
    graph_store.get_related_nodes.return_value = []
    retriever = HybridRetriever(vector_store=vector_store, graph_store=graph_store, embedder=embedder)
    results = retriever.search("query", mode="hybrid", top_k=5)
    # Both stores should be called in hybrid mode
    vector_store.search.assert_called()
    graph_store.query_graph.assert_called()
    # Results should be a list of dicts
    assert isinstance(results, list)
