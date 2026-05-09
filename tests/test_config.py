"""Tests for config module."""

from src.config import (
    SUPPORTED_EXTENSIONS,
    COMMENT_NODE_TYPES,
    EMBEDDING_DIMENSIONS,
)


def test_supported_extensions():
    expected_extensions = {".js", ".jsx", ".mjs", ".cjs", ".ts", ".tsx", ".mts", ".cts"}
    assert set(SUPPORTED_EXTENSIONS.keys()) == expected_extensions


def test_embedding_dimensions_value():
    assert EMBEDDING_DIMENSIONS == 3584


def test_comment_node_types_is_tuple_with_three_elements():
    assert isinstance(COMMENT_NODE_TYPES, tuple)
    assert len(COMMENT_NODE_TYPES) == 3
