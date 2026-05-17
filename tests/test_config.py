"""Tests for config module."""

from src.config import (
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
