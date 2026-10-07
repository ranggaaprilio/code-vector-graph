"""Tests for config module."""

from code_vector_graph.config import (
    SUPPORTED_EXTENSIONS,
    COMMENT_NODE_TYPES,
    EMBEDDING_DIMENSIONS,
    MODEL_CONFIGS,
    DEFAULT_MODEL_ID,
    get_model_config,
)


def test_supported_extensions():
    expected_extensions = {".js", ".jsx", ".mjs", ".cjs", ".ts", ".tsx", ".mts", ".cts"}
    assert set(SUPPORTED_EXTENSIONS.keys()) == expected_extensions


def test_model_configs_contains_both_models():
    assert "nomic" in MODEL_CONFIGS
    assert "jina" in MODEL_CONFIGS


def test_default_model_dimensions():
    assert EMBEDDING_DIMENSIONS == MODEL_CONFIGS[DEFAULT_MODEL_ID]["dimensions"]


def test_nomic_config():
    cfg = get_model_config("nomic")
    assert cfg["model_name"] == "nomic-ai/nomic-embed-code"
    assert cfg["dimensions"] == 3584
    assert cfg["dtype"] == "float16"
    assert cfg["prefixes"] is None


def test_jina_config():
    cfg = get_model_config("jina")
    assert cfg["model_name"] == "jinaai/jina-code-embeddings-1.5b"
    assert cfg["dimensions"] == 1536
    assert cfg["dtype"] == "bfloat16"
    assert cfg["prefixes"] is not None
    assert "code2code" in cfg["prefixes"]
    assert "nl2code" in cfg["prefixes"]


def test_get_model_config_invalid():
    try:
        get_model_config("nonexistent")
        assert False, "Should have raised ValueError"
    except ValueError:
        pass


def test_comment_node_types_is_tuple_with_three_elements():
    assert isinstance(COMMENT_NODE_TYPES, tuple)
    assert len(COMMENT_NODE_TYPES) == 3


# --- active collection / env overrides ---

def test_active_collection_defaults(monkeypatch):
    from code_vector_graph.config import DEFAULT_BASE_COLLECTION, active_collection

    monkeypatch.delenv("CVG_MODEL_ID", raising=False)
    monkeypatch.delenv("CVG_COLLECTION_NAME", raising=False)
    # `active_model_id()` falls back to EMBEDDING_MODEL_ID before the hardcoded
    # "nomic" default — clear it so this test exercises that hardcoded default
    # regardless of what an earlier test's `load_dotenv()` left in os.environ.
    monkeypatch.delenv("EMBEDDING_MODEL_ID", raising=False)
    name, dims, model_id = active_collection()
    assert model_id == "nomic"
    assert dims == MODEL_CONFIGS["nomic"]["dimensions"]
    assert name.startswith(DEFAULT_BASE_COLLECTION + "_")
    assert name.endswith(f"_{dims}")


def test_active_collection_honors_env(monkeypatch):
    from code_vector_graph.config import active_base_collection, active_collection, active_model_id

    monkeypatch.setenv("CVG_MODEL_ID", "jina")
    monkeypatch.setenv("CVG_COLLECTION_NAME", "scratch")
    assert active_model_id() == "jina"
    assert active_base_collection() == "scratch"
    assert active_collection() == ("scratch_jina-code-embeddings-1.5b_1536", 1536, "jina")


def test_active_model_id_invalid(monkeypatch):
    from code_vector_graph.config import active_model_id

    monkeypatch.setenv("CVG_MODEL_ID", "nope")
    try:
        active_model_id()
        assert False, "Should have raised ValueError"
    except ValueError:
        pass
