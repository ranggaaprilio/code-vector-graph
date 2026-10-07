import logging
from typing import List, Dict, Optional, Tuple

logger = logging.getLogger(__name__)


def reciprocal_rank_fusion(ranked_lists: List[List[Tuple[str, float]]], k: int = 60,
                          weights: Optional[List[float]] = None) -> List[Tuple[str, float]]:
    """Simple Reciprocal Rank Fusion over multiple ranked lists.

    ranked_lists: a list of rankings. Each ranking is a list of (doc_id, score)
    k: smoothing parameter for the fusion formula
    weights: per-list weights. If None, defaults to equal weighting 0.7/0.3 for two lists.
    Returns a list of (doc_id, fused_score) sorted by fused_score desc.
    """
    if weights is None:
        weights = [0.7, 0.3]

    fused: Dict[str, float] = {}
    for list_idx, ranking in enumerate(ranked_lists):
        weight = weights[list_idx] if list_idx < len(weights) else 0.0
        for rank, (doc_id, _score) in enumerate(ranking, start=1):
            score = weight / (k + rank)
            fused[doc_id] = fused.get(doc_id, 0.0) + score

    # Convert to list and sort by score desc
    return sorted(fused.items(), key=lambda x: -x[1])


def _records_of(result):
    """Neo4j's execute_query returns an EagerResult (.records); doubles return plain lists."""
    if result is None:
        return []
    return result.records if hasattr(result, "records") else result


def _node_to_dict(node) -> Dict:
    """Coerce a neo4j Node (or a plain dict / None) into a plain dict of properties."""
    if node is None:
        return {}
    if isinstance(node, dict):
        return dict(node)
    if hasattr(node, "items"):
        return dict(node.items())
    return {}


def _related_to_context(raw) -> List[Dict]:
    """Serialize get_related_nodes() output into JSON-safe {id, labels, name} dicts."""
    context: List[Dict] = []
    for rec in _records_of(raw):
        get = rec.get if hasattr(rec, "get") else None
        node = get("related") if get is not None else None
        if node is None and isinstance(rec, dict):
            node = rec
        props = _node_to_dict(node)
        if not props and node is None:
            continue
        labels = list(getattr(node, "labels", []) or props.get("labels") or [])
        context.append({
            "id": props.get("id") or (str(getattr(node, "element_id", "")) or None),
            "labels": labels,
            "name": props.get("name") or props.get("path") or props.get("title"),
        })
    return context


class HybridRetriever:
    def __init__(self, vector_store, graph_store, embedder=None):
        # Interfaces are kept generic to accommodate test doubles
        self.vector_store = vector_store
        self.graph_store = graph_store
        self.embedder = embedder

        # Convenience: store a short-lived pointer for reuse
        self._last_vector_results: Dict[str, Dict] = {}

    def search(self, query: str, mode: str = "hybrid", top_k: int = 20,
               vector_weight: float = 0.7, graph_weight: float = 0.3,
               query_vec=None, query_filter=None):
        mode = mode.lower()
        if mode == "vector":
            return self._vector_search(query, top_k, query_vec=query_vec, query_filter=query_filter)
        if mode == "graph":
            return self._graph_search(query, top_k)
        # default: hybrid
        return self._hybrid_search(query, top_k, vector_weight, graph_weight,
                                   query_vec=query_vec, query_filter=query_filter)

    def _vector_search(self, query: str, top_k: int, query_vec=None, query_filter=None) -> List[Dict]:
        """Search vector store for query.

        Args:
            query: The search query string
            top_k: Number of results to return
            query_vec: Optional pre-computed query embedding to avoid re-embedding
            query_filter: Optional Qdrant Filter forwarded to the vector store

        Returns:
            List of result dicts with keys: id, payload, score, graph_context
        """
        try:
            if query_vec is None and self.embedder is not None:
                query_vec = self.embedder.embed_query(query)
            results = self.vector_store.search(query_vec, top_k=top_k, query_filter=query_filter)
        except (ConnectionError, ValueError, AttributeError) as e:
            logger.warning(f"Vector search failed: {e}")
            return []

        items = []
        for r in results:
            # Normalize to a common shape
            doc_id = None
            payload = None
            score = None
            if isinstance(r, dict):
                doc_id = r.get("id") or r.get("doc_id") or r.get("_id")
                payload = r.get("payload")
                score = r.get("score")
            else:
                # Fallback: assume tuple (id, payload, score) or (id, score)
                if isinstance(r, tuple) and len(r) == 3:
                    doc_id = r[0]
                    payload = r[1]
                    score = r[2]
                elif isinstance(r, tuple) and len(r) == 2:
                    doc_id = r[0]
                    score = r[1]

            items.append({"id": doc_id, "payload": payload, "score": score, "graph_context": None})
            if doc_id is not None:
                self._last_vector_results[doc_id] = {"payload": payload, "score": score}

        # Ensure a consistent return type: list of dicts with keys id/payload/score
        return items

    def _graph_search(self, query: str, top_k: int) -> List[Dict]:
        """Search graph store for query.
        
        Args:
            query: The search query string
            top_k: Number of results to return
            
        Returns:
            List of result dicts with keys: id, payload, score, graph_context
        """
        try:
            # Simple, tests-friendly cypher-like query. Implementation detail kept generic.
            cypher = (
                "MATCH (n) WHERE toLower(n.name) CONTAINS toLower($query) "
                "RETURN n.id AS id, n AS node LIMIT $limit"
            )
            params = {"query": query, "limit": top_k}
            results = self.graph_store.query_graph(cypher, params)
        except (ConnectionError, ValueError, AttributeError) as e:
            logger.warning(f"Graph search failed: {e}")
            return []

        items = []
        for r in _records_of(results):
            get = r.get if hasattr(r, "get") else None
            if get is None:
                continue
            doc_id = get("id")
            payload = _node_to_dict(get("node"))
            score = get("score", 1.0)
            items.append({"id": doc_id, "payload": payload, "score": score, "graph_context": None})
        return items

    def _hybrid_search(self, query: str, top_k: int, vector_weight: float, graph_weight: float,
                       query_vec=None, query_filter=None) -> List[Dict]:
        """Perform hybrid search combining vector and graph results using RRF."""
        vector_top = max(1, top_k * 2)
        vector_results = self._vector_search(query, vector_top, query_vec=query_vec, query_filter=query_filter)
        graph_results = self._graph_search(query, vector_top)

        vector_ranked = [(r["id"], r.get("score", 0.0)) for r in vector_results if r.get("id") is not None]
        graph_ranked = [(r["id"], r.get("score", 0.0)) for r in graph_results if r.get("id") is not None]

        fused = reciprocal_rank_fusion([
            vector_ranked,
            graph_ranked
        ], k=60, weights=[vector_weight, graph_weight])

        # O(1) lookup instead of O(N) linear scan per result
        vector_map: Dict[str, Dict] = {r["id"]: r for r in vector_results if r.get("id") is not None}

        results: List[Dict] = []
        seen = set()
        for doc_id, fused_score in fused:
            if doc_id in seen:
                continue
            seen.add(doc_id)
            enriched = self._enrich_result(doc_id, fused_score, vector_map)
            results.append(enriched)
            if len(results) >= top_k:
                break
        return results

    def _enrich_result(self, doc_id: str, fused_score: float, vector_map: Dict[str, Dict]) -> Dict:
        vec = vector_map.get(doc_id)
        payload = vec.get("payload", {}) or {} if vec is not None else {}

        graph_context: List[Dict] = []
        try:
            if hasattr(self.graph_store, "get_related_nodes"):
                raw = self.graph_store.get_related_nodes(doc_id, depth=1, limit=5)
                graph_context = _related_to_context(raw)
        except (ConnectionError, ValueError, AttributeError) as e:
            logger.warning(f"Graph context enrichment failed for {doc_id}: {e}")

        return {
            "id": doc_id,
            "score": fused_score,
            "payload": payload,
            "graph_context": graph_context,
        }
