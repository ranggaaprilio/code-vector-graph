"""Qdrant VectorStore implementation with deterministic IDs."""

import logging
import uuid
from typing import Any

from qdrant_client import QdrantClient
from qdrant_client.models import Distance, Filter, PayloadSchemaType, PointStruct, VectorParams

from src.config import (
    DEFAULT_COLLECTION_NAME,
    DEFAULT_QDRANT_URL,
    EMBEDDING_DIMENSIONS,
    EMBEDDING_PROVIDERS,
    MODEL_CONFIGS,
)

logger = logging.getLogger(__name__)


def get_collection_name(base_name: str, provider: str, model: str | None = None) -> str:
    """Generate collection name based on provider and model.

    Format: {base_name}_{model_suffix}_{dimensions}

    Examples:
        - huggingface + nomic-embed-code → code_chunks_nomic-embed-code_3584
        - huggingface + jina-code-embeddings-1.5b → code_chunks_jina-code-embeddings-1.5b_1536
    """
    provider_config = EMBEDDING_PROVIDERS[provider]
    model_name = model or provider_config["model"]

    dimensions = provider_config["dimensions"]
    for cfg in MODEL_CONFIGS.values():
        if cfg["model_name"] == model_name:
            dimensions = cfg["dimensions"]
            break

    # Clean model name (remove special chars, take last part if has /)
    if "/" in model_name:
        model_name = model_name.split("/")[-1]
    if ":" in model_name:
        model_name = model_name.split(":")[0]

    return f"{base_name}_{model_name}_{dimensions}"


class VectorStore:
    """Qdrant vector store with deterministic UUID5 IDs."""

    def __init__(
        self,
        collection_name: str = DEFAULT_COLLECTION_NAME,
        qdrant_url: str = DEFAULT_QDRANT_URL,
        embedding_dimensions: int = EMBEDDING_DIMENSIONS,
    ):
        """
        Initialize VectorStore with Qdrant connection.

        Args:
            collection_name: Name of the Qdrant collection
            qdrant_url: URL of the Qdrant server (use ":memory:" for in-memory mode)
            embedding_dimensions: Size of embedding vectors (dynamically set based on provider)
        """
        self.collection_name = collection_name
        self.embedding_dimensions = embedding_dimensions

        if qdrant_url == ":memory:":
            self.client = QdrantClient(":memory:")
        else:
            self.client = QdrantClient(url=qdrant_url)

        logger.debug(
            f"Initialized VectorStore for collection '{collection_name}' at {qdrant_url}"
        )

    def check_health(self) -> bool:
        """
        Check if Qdrant is reachable.

        Returns:
            True if Qdrant is reachable, False otherwise
        """
        try:
            self.client.get_collections()
            logger.debug("Qdrant health check: OK")
            return True
        except Exception as e:
            logger.error(f"Qdrant health check failed: {e}")
            return False

    def _ensure_indexes(self) -> None:
        """
        Create payload indexes for optimized filtering.

        Creates indexes for all metadata fields used in queries.
        Handles already-existing indexes gracefully.
        """
        indexes = [
            ("file_path", PayloadSchemaType.KEYWORD),
            ("language", PayloadSchemaType.KEYWORD),
            ("node_type", PayloadSchemaType.KEYWORD),
            ("class_name", PayloadSchemaType.KEYWORD),
            ("function_name", PayloadSchemaType.KEYWORD),
            ("imports", PayloadSchemaType.KEYWORD),
            ("exports", PayloadSchemaType.KEYWORD),
            ("call_sites", PayloadSchemaType.KEYWORD),
            ("is_exported", PayloadSchemaType.BOOL),
            ("visibility", PayloadSchemaType.KEYWORD),
            ("file_hash", PayloadSchemaType.KEYWORD),
            ("term", PayloadSchemaType.KEYWORD),
            ("kind", PayloadSchemaType.KEYWORD),
            ("source", PayloadSchemaType.KEYWORD),
            ("symbol_id", PayloadSchemaType.KEYWORD),
        ]

        for field_name, schema_type in indexes:
            try:
                self.client.create_payload_index(
                    collection_name=self.collection_name,
                    field_name=field_name,
                    field_schema=schema_type,
                )
                logger.debug(f"Created index for '{field_name}' ({schema_type.value})")
            except Exception as e:
                # Index may already exist, which is fine
                logger.debug(f"Index for '{field_name}' may already exist: {e}")

    def create_collection(self) -> None:
        """
        Create collection with VectorParams(size={self.embedding_dimensions}, distance=Distance.COSINE).

        If collection already exists, this is a no-op.
        """
        try:
            if self.client.collection_exists(self.collection_name):
                logger.info(f"Collection '{self.collection_name}' already exists")
                self._ensure_indexes()
                return

            self.client.create_collection(
                collection_name=self.collection_name,
                vectors_config=VectorParams(
                    size=self.embedding_dimensions,
                    distance=Distance.COSINE,
                ),
            )
            logger.info(
                f"Created collection '{self.collection_name}' with {self.embedding_dimensions} dimensions (COSINE)"
            )
            self._ensure_indexes()
        except Exception as e:
            logger.error(f"Failed to create collection: {e}")
            raise

    def _generate_deterministic_id(
        self, file_path: str, chunk_index: int, file_hash: str = ""
    ) -> str:
        """
        Generate deterministic UUID5 ID from file path, chunk index, and file hash.

        Args:
            file_path: Path to the source file
            chunk_index: Index of the chunk within the file
            file_hash: Hash of the file content for cache invalidation

        Returns:
            UUID5 string
        """
        namespace = uuid.NAMESPACE_URL
        name = f"{file_path}:{chunk_index}:{file_hash}"
        return str(uuid.uuid5(namespace, name))

    def _chunk_to_point(self, chunk: dict[str, Any]) -> PointStruct:
        """
        Convert chunk dict to Qdrant PointStruct.

        Args:
            chunk: Dictionary with chunk data including:
                - file_path: str
                - chunk_index: int
                - embedding: list[float] ({self.embedding_dimensions} dimensions)
                - language: str
                - start_line: int
                - end_line: int
                - function_name: str | None
                - total_chunks: int
                - text_content: str
                - node_type: str | None
                - class_name: str | None
                - parent_function: str | None
                - imports: list[str]
                - exports: list[str]
                - symbols_defined: list[str]
                - call_sites: list[str]
                - is_exported: bool
                - visibility: str | None
                - nesting_depth: int
                - token_count: int
                - decorators: list[str]
                - file_hash: str
                - graph_nodes: list[dict]
                - graph_relationships: list[dict]

        Returns:
            PointStruct for Qdrant upsert
        """
        file_path = chunk["file_path"]
        chunk_index = chunk["chunk_index"]
        file_hash = chunk.get("file_hash", "")

        point_id = chunk.get("id") or self._generate_deterministic_id(file_path, chunk_index, file_hash)

        payload = {
            "file_path": file_path,
            "language": chunk["language"],
            "start_line": chunk["start_line"],
            "end_line": chunk["end_line"],
            "chunk_index": chunk_index,
            "function_name": chunk.get("function_name"),
            "total_chunks": chunk["total_chunks"],
            "text_content": chunk["text_content"],
            "node_type": chunk.get("node_type"),
            "class_name": chunk.get("class_name"),
            "parent_function": chunk.get("parent_function"),
            "imports": chunk.get("imports", []),
            "exports": chunk.get("exports", []),
            "symbols_defined": chunk.get("symbols_defined", []),
            "call_sites": chunk.get("call_sites", []),
            "is_exported": chunk.get("is_exported", False),
            "visibility": chunk.get("visibility"),
            "nesting_depth": chunk.get("nesting_depth", 0),
            "token_count": chunk.get("token_count", 0),
            "decorators": chunk.get("decorators", []),
            "file_hash": file_hash,
            "graph_nodes": chunk.get("graph_nodes", []),
            "graph_relationships": chunk.get("graph_relationships", []),
            "term": chunk.get("term"),
            "kind": chunk.get("kind"),
            "summary": chunk.get("summary"),
            "source": chunk.get("source"),
            "confidence": chunk.get("confidence"),
            "symbol_id": chunk.get("symbol_id"),
        }

        return PointStruct(
            id=point_id,
            vector=chunk["embedding"],
            payload=payload,
        )

    def upsert_chunks(
        self, chunks: list[dict[str, Any]], batch_size: int = 100
    ) -> list[str]:
        """
        Upsert chunks to Qdrant in batches with deterministic IDs.

        Args:
            chunks: List of chunk dictionaries
            batch_size: Number of points per batch

        Returns:
            List of point IDs that were upserted
        """
        if not chunks:
            logger.info("No chunks to upsert")
            return []

        points = [self._chunk_to_point(chunk) for chunk in chunks]
        point_ids = [point.id for point in points]

        total_batches = (len(points) + batch_size - 1) // batch_size

        for batch_idx in range(total_batches):
            start_idx = batch_idx * batch_size
            end_idx = min(start_idx + batch_size, len(points))
            batch = points[start_idx:end_idx]

            logger.info(
                f"Upserting batch {batch_idx + 1}/{total_batches} ({len(batch)} points)"
            )

            self.client.upsert(
                collection_name=self.collection_name,
                points=batch,
            )

        logger.info(f"Successfully upserted {len(points)} chunks")
        return point_ids

    def search(self, vector: list[float], top_k: int = 20, query_filter: Filter | None = None) -> list[dict[str, Any]]:
        """
        Search for similar vectors in the collection.

        Args:
            vector: Query embedding vector
            top_k: Number of results to return
            query_filter: Optional Qdrant Filter for metadata filtering

        Returns:
            List of result dicts with 'id', 'payload', and 'score' keys
        """
        try:
            kwargs: dict[str, Any] = {
                "collection_name": self.collection_name,
                "query": vector,
                "limit": top_k,
                "with_payload": True,
            }
            if query_filter is not None:
                kwargs["query_filter"] = query_filter
            search_result = self.client.query_points(**kwargs).points
            return [
                {
                    "id": point.id,
                    "payload": point.payload,
                    "score": point.score,
                }
                for point in search_result
            ]
        except Exception as e:
            logger.error(f"Search failed: {e}")
            raise

    def get_point(self, point_id: str) -> dict[str, Any] | None:
        """
        Retrieve a point by ID for verification.

        Args:
            point_id: The UUID of the point to retrieve

        Returns:
            Point data dict or None if not found
        """
        try:
            points = self.client.retrieve(
                collection_name=self.collection_name,
                ids=[point_id],
            )
            if points:
                point = points[0]
                return {
                    "id": point.id,
                    "vector": point.vector,
                    "payload": point.payload,
                }
            return None
        except Exception as e:
            logger.error(f"Failed to retrieve point {point_id}: {e}")
            return None
