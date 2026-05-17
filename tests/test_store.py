"""Tests for VectorStore Qdrant integration."""

import pytest
from qdrant_client import QdrantClient
from qdrant_client.models import Distance

from src.store import VectorStore


@pytest.fixture
def in_memory_store():
    """Create a VectorStore using in-memory Qdrant for testing."""
    store = VectorStore(
        collection_name="test_collection",
        qdrant_url=":memory:",
        embedding_dimensions=1536,
    )
    return store


@pytest.fixture
def sample_chunks():
    """Create sample chunks for testing."""
    return [
        {
            "file_path": "/test/file1.js",
            "chunk_index": 0,
            "embedding": [0.1] * 1536,
            "language": "javascript",
            "start_line": 1,
            "end_line": 10,
            "function_name": "testFunc",
            "total_chunks": 2,
            "text_content": "function testFunc() { return 1; }",
        },
        {
            "file_path": "/test/file1.js",
            "chunk_index": 1,
            "embedding": [0.2] * 1536,
            "language": "javascript",
            "start_line": 11,
            "end_line": 20,
            "function_name": "anotherFunc",
            "total_chunks": 2,
            "text_content": "function anotherFunc() { return 2; }",
        },
        {
            "file_path": "/test/file2.ts",
            "chunk_index": 0,
            "embedding": [0.3] * 1536,
            "language": "typescript",
            "start_line": 1,
            "end_line": 5,
            "function_name": None,
            "total_chunks": 1,
            "text_content": "const x = 1;",
        },
    ]


class TestVectorStoreInit:
    """Test VectorStore initialization."""

    def test_init_with_defaults(self):
        """Test initialization with default parameters."""
        store = VectorStore()
        assert store.collection_name == "code_chunks"
        assert store.embedding_dimensions == 1536

    def test_init_with_custom_params(self):
        """Test initialization with custom parameters."""
        store = VectorStore(
            collection_name="custom_collection",
            qdrant_url="http://custom:6333",
            embedding_dimensions=512,
        )
        assert store.collection_name == "custom_collection"
        assert store.embedding_dimensions == 512

    def test_client_is_qdrant_client(self, in_memory_store):
        """Test that client is a QdrantClient instance."""
        assert isinstance(in_memory_store.client, QdrantClient)


class TestCheckHealth:
    """Test health check functionality."""

    def test_check_health_success(self, in_memory_store):
        """Test health check with reachable Qdrant."""
        assert in_memory_store.check_health() is True


class TestCreateCollection:
    """Test collection creation."""

    def test_create_collection_with_correct_params(self, in_memory_store):
        """Test collection is created with 1536 dimensions and COSINE distance."""
        in_memory_store.create_collection()

        info = in_memory_store.client.get_collection("test_collection")
        config = info.config.params.vectors

        assert config.size == 1536
        assert config.distance == Distance.COSINE

    def test_create_collection_idempotent(self, in_memory_store):
        """Test that create_collection is idempotent (no error if exists)."""
        in_memory_store.create_collection()
        in_memory_store.create_collection()

        info = in_memory_store.client.get_collection("test_collection")
        assert info is not None


class TestUpsertChunks:
    """Test chunk upsertion."""

    def test_upsert_returns_ids(self, in_memory_store, sample_chunks):
        """Test upsert returns list of point IDs."""
        in_memory_store.create_collection()
        ids = in_memory_store.upsert_chunks(sample_chunks)

        assert len(ids) == 3
        assert all(isinstance(id_, str) for id_ in ids)

    def test_upsert_empty_list(self, in_memory_store):
        """Test upsert with empty list returns empty list."""
        in_memory_store.create_collection()
        ids = in_memory_store.upsert_chunks([])
        assert ids == []

    def test_deterministic_ids(self, in_memory_store, sample_chunks):
        """Test that same input produces same IDs (deterministic UUID5)."""
        in_memory_store.create_collection()

        ids1 = in_memory_store.upsert_chunks(sample_chunks)
        ids2 = in_memory_store.upsert_chunks(sample_chunks)

        assert ids1 == ids2

    def test_upsert_updates_existing(self, in_memory_store, sample_chunks):
        """Test that upsert updates existing points, not duplicates."""
        in_memory_store.create_collection()

        in_memory_store.upsert_chunks(sample_chunks)
        in_memory_store.upsert_chunks(sample_chunks)

        collection_info = in_memory_store.client.get_collection("test_collection")
        assert collection_info.points_count == 3

    def test_batch_processing(self, in_memory_store):
        """Test that batch processing works correctly."""
        in_memory_store.create_collection()

        chunks = [
            {
                "file_path": f"/test/file{i}.js",
                "chunk_index": 0,
                "embedding": [0.1] * 1536,
                "language": "javascript",
                "start_line": 1,
                "end_line": 10,
                "function_name": None,
                "total_chunks": 1,
                "text_content": f"code {i}",
            }
            for i in range(5)
        ]

        ids = in_memory_store.upsert_chunks(chunks, batch_size=2)
        assert len(ids) == 5


class TestMetadataPayload:
    """Test metadata payload structure."""

    def test_payload_has_all_required_fields(self, in_memory_store, sample_chunks):
        """Test that metadata payload contains all required fields."""
        in_memory_store.create_collection()
        ids = in_memory_store.upsert_chunks(sample_chunks)

        point = in_memory_store.get_point(ids[0])
        assert point is not None

        payload = point["payload"]
        required_fields = [
            "file_path",
            "language",
            "start_line",
            "end_line",
            "chunk_index",
            "function_name",
            "total_chunks",
            "text_content",
            "graph_nodes",
            "graph_relationships",
        ]

        for field in required_fields:
            assert field in payload, f"Missing field: {field}"

    def test_payload_values_correct(self, in_memory_store, sample_chunks):
        """Test that payload values match input data."""
        in_memory_store.create_collection()
        ids = in_memory_store.upsert_chunks(sample_chunks)

        point = in_memory_store.get_point(ids[0])
        payload = point["payload"]

        assert payload["file_path"] == "/test/file1.js"
        assert payload["language"] == "javascript"
        assert payload["start_line"] == 1
        assert payload["end_line"] == 10
        assert payload["chunk_index"] == 0
        assert payload["function_name"] == "testFunc"
        assert payload["total_chunks"] == 2
        assert payload["text_content"] == "function testFunc() { return 1; }"
        assert payload["graph_nodes"] == []
        assert payload["graph_relationships"] == []

    def test_glossary_payload_values(self, in_memory_store):
        in_memory_store.create_collection()
        chunks = [
            {
                "id": "11111111-1111-5111-8111-111111111111",
                "file_path": "/test/file1.js",
                "chunk_index": 0,
                "embedding": [0.1] * 768,
                "language": "javascript",
                "start_line": 0,
                "end_line": 0,
                "function_name": None,
                "total_chunks": 1,
                "node_type": "glossary_entry",
                "text_content": "userId (variable): User identifier.",
                "term": "userId",
                "kind": "variable",
                "summary": "User identifier.",
                "source": "manual",
                "confidence": 1.0,
                "symbol_id": "symbol-1",
            }
        ]

        ids = in_memory_store.upsert_chunks(chunks)
        point = in_memory_store.get_point(ids[0])
        payload = point["payload"]

        assert ids == ["11111111-1111-5111-8111-111111111111"]
        assert payload["node_type"] == "glossary_entry"
        assert payload["term"] == "userId"
        assert payload["kind"] == "variable"
        assert payload["summary"] == "User identifier."
        assert payload["source"] == "manual"
        assert payload["symbol_id"] == "symbol-1"

    def test_null_function_name(self, in_memory_store, sample_chunks):
        """Test that null function_name is preserved."""
        in_memory_store.create_collection()
        ids = in_memory_store.upsert_chunks(sample_chunks)

        point = in_memory_store.get_point(ids[2])
        assert point["payload"]["function_name"] is None


class TestGetPoint:
    """Test point retrieval."""

    def test_get_point_existing(self, in_memory_store, sample_chunks):
        """Test retrieving an existing point."""
        in_memory_store.create_collection()
        ids = in_memory_store.upsert_chunks(sample_chunks)

        point = in_memory_store.get_point(ids[0])
        assert point is not None
        assert point["id"] == ids[0]
        assert "vector" in point
        assert "payload" in point

    def test_get_point_nonexistent(self, in_memory_store):
        """Test retrieving a non-existent point returns None."""
        in_memory_store.create_collection()

        point = in_memory_store.get_point("nonexistent-id")
        assert point is None


class TestDeterministicIDGeneration:
    """Test deterministic ID generation logic."""

    def test_same_input_same_id(self, in_memory_store):
        """Test that same file_path and chunk_index produce same ID."""
        id1 = in_memory_store._generate_deterministic_id("/path/to/file.js", 5)
        id2 = in_memory_store._generate_deterministic_id("/path/to/file.js", 5)

        assert id1 == id2

    def test_different_path_different_id(self, in_memory_store):
        """Test that different file_paths produce different IDs."""
        id1 = in_memory_store._generate_deterministic_id("/path/to/file1.js", 0)
        id2 = in_memory_store._generate_deterministic_id("/path/to/file2.js", 0)

        assert id1 != id2

    def test_different_index_different_id(self, in_memory_store):
        """Test that different chunk indices produce different IDs."""
        id1 = in_memory_store._generate_deterministic_id("/path/to/file.js", 0)
        id2 = in_memory_store._generate_deterministic_id("/path/to/file.js", 1)

        assert id1 != id2

    def test_id_is_valid_uuid(self, in_memory_store):
        """Test that generated IDs are valid UUID5 strings."""
        import uuid

        id_str = in_memory_store._generate_deterministic_id("/path/to/file.js", 0)
        parsed = uuid.UUID(id_str)

        assert parsed.version == 5
