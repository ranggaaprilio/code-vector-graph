"""Tests for the embedder module."""

from unittest.mock import MagicMock, patch

import pytest
import torch

from src.config import MODEL_CONFIGS, DEFAULT_MODEL_ID
from src.embedder import HuggingFaceEmbedder, create_embedder, JINA_TASK_PREFIXES


def _mock_embedder_init(model_id=None):
    """Helper to create mock embedder without full init."""
    model_id = model_id or DEFAULT_MODEL_ID
    config = MODEL_CONFIGS[model_id]
    embedder = object.__new__(HuggingFaceEmbedder)
    embedder.model_id = model_id
    embedder.model_config = config
    embedder.model_name = config["model_name"]
    embedder.prefixes = config["prefixes"]
    embedder.dimensions = config["dimensions"]
    embedder.device = "cpu"
    return embedder


class TestHuggingFaceEmbedderInit:
    @patch("src.embedder.AutoTokenizer")
    @patch("src.embedder.AutoModel")
    def test_init_with_defaults(self, mock_model_class, mock_tokenizer_class):
        mock_tokenizer = MagicMock()
        mock_model = MagicMock()
        mock_tokenizer_class.from_pretrained.return_value = mock_tokenizer
        mock_model_class.from_pretrained.return_value = mock_model

        embedder = HuggingFaceEmbedder()

        assert embedder.model_name == MODEL_CONFIGS[DEFAULT_MODEL_ID]["model_name"]
        assert embedder.device == "cpu"
        assert embedder.model_id == DEFAULT_MODEL_ID
        mock_model.eval.assert_called_once()

    @patch("src.embedder.AutoTokenizer")
    @patch("src.embedder.AutoModel")
    def test_init_with_model_id(self, mock_model_class, mock_tokenizer_class):
        mock_tokenizer = MagicMock()
        mock_model = MagicMock()
        mock_tokenizer_class.from_pretrained.return_value = mock_tokenizer
        mock_model_class.from_pretrained.return_value = mock_model

        embedder = HuggingFaceEmbedder(model_id="jina")

        assert embedder.model_name == "jinaai/jina-code-embeddings-1.5b"
        assert embedder.model_id == "jina"

    @patch("src.embedder.AutoTokenizer")
    @patch("src.embedder.AutoModel")
    def test_init_with_custom_device(self, mock_model_class, mock_tokenizer_class):
        mock_tokenizer = MagicMock()
        mock_model = MagicMock()
        mock_tokenizer_class.from_pretrained.return_value = mock_tokenizer
        mock_model_class.from_pretrained.return_value = mock_model

        embedder = HuggingFaceEmbedder(device="cuda")

        assert embedder.device == "cuda"


class TestPrefixLogic:
    def test_nomic_no_prefix_for_passage(self):
        embedder = _mock_embedder_init(model_id="nomic")
        texts = ["def foo(): pass"]
        result = embedder._prepend_passage_prefix(texts)
        assert result == texts

    def test_nomic_no_prefix_for_query(self):
        embedder = _mock_embedder_init(model_id="nomic")
        query = "find a function"
        result = embedder._prepend_query_prefix(query)
        assert result == query

    def test_jina_prefix_for_passage(self):
        embedder = _mock_embedder_init(model_id="jina")
        texts = ["def foo(): pass"]
        result = embedder._prepend_passage_prefix(texts)
        expected_prefix = JINA_TASK_PREFIXES["code2code"]["passage"]
        assert result[0].startswith(expected_prefix)

    def test_jina_prefix_for_query(self):
        embedder = _mock_embedder_init(model_id="jina")
        query = "find a function"
        result = embedder._prepend_query_prefix(query)
        expected_prefix = JINA_TASK_PREFIXES["nl2code"]["query"]
        assert result.startswith(expected_prefix)


class TestHuggingFaceEmbedderEmbedChunks:
    @patch("src.embedder.AutoTokenizer")
    @patch("src.embedder.AutoModel")
    def test_embed_chunks_returns_embeddings(self, mock_model_class, mock_tokenizer_class):
        mock_tokenizer = MagicMock()
        mock_model = MagicMock()
        mock_tokenizer_class.from_pretrained.return_value = mock_tokenizer
        mock_model_class.from_pretrained.return_value = mock_model

        embedder = HuggingFaceEmbedder()

        chunks = [
            {"text": "def foo(): pass"},
            {"text": "class Bar: pass"},
        ]

        dimensions = embedder.dimensions

        def mock_tokenize(texts, **kwargs):
            batch_size = len(texts)
            return {
                "input_ids": torch.ones(batch_size, 10, dtype=torch.long),
                "attention_mask": torch.ones(batch_size, 10, dtype=torch.long),
            }

        mock_tokenizer.side_effect = mock_tokenize

        def mock_forward(**kwargs):
            batch_size = kwargs["input_ids"].shape[0]
            output = MagicMock()
            output.last_hidden_state = torch.randn(batch_size, 10, dimensions)
            return output

        mock_model.side_effect = mock_forward

        result = embedder.embed_chunks(chunks)

        assert len(result) == 2
        assert "embedding" in result[0]
        assert "embedding" in result[1]
        assert len(result[0]["embedding"]) == dimensions
        assert len(result[1]["embedding"]) == dimensions

    @patch("src.embedder.AutoTokenizer")
    @patch("src.embedder.AutoModel")
    def test_embed_chunks_empty_list(self, mock_model_class, mock_tokenizer_class):
        mock_tokenizer = MagicMock()
        mock_model = MagicMock()
        mock_tokenizer_class.from_pretrained.return_value = mock_tokenizer
        mock_model_class.from_pretrained.return_value = mock_model

        embedder = HuggingFaceEmbedder()
        result = embedder.embed_chunks([])

        assert result == []
        mock_tokenizer.assert_not_called()
        mock_model.assert_not_called()

    @patch("src.embedder.AutoTokenizer")
    @patch("src.embedder.AutoModel")
    def test_embed_chunks_nomic_no_prefix(self, mock_model_class, mock_tokenizer_class):
        mock_tokenizer = MagicMock()
        mock_model = MagicMock()
        mock_tokenizer_class.from_pretrained.return_value = mock_tokenizer
        mock_model_class.from_pretrained.return_value = mock_model

        embedder = HuggingFaceEmbedder()

        chunks = [{"text": "def foo(): pass"}]

        mock_inputs = {
            "input_ids": torch.tensor([[1, 2, 3]]),
            "attention_mask": torch.tensor([[1, 1, 1]]),
        }
        mock_tokenizer.return_value = mock_inputs

        mock_outputs = MagicMock()
        mock_outputs.last_hidden_state = torch.randn(1, 3, embedder.dimensions)
        mock_model.return_value = mock_outputs

        embedder.embed_chunks(chunks)

        call_args = mock_tokenizer.call_args
        passed_texts = call_args[0][0] if call_args[0] else call_args[1].get("texts", [])
        assert passed_texts[0] == "def foo(): pass"

    @patch("src.embedder.AutoTokenizer")
    @patch("src.embedder.AutoModel")
    def test_embed_chunks_jina_with_prefix(self, mock_model_class, mock_tokenizer_class):
        mock_tokenizer = MagicMock()
        mock_model = MagicMock()
        mock_tokenizer_class.from_pretrained.return_value = mock_tokenizer
        mock_model_class.from_pretrained.return_value = mock_model

        embedder = HuggingFaceEmbedder(model_id="jina")

        chunks = [{"text": "def foo(): pass"}]

        mock_inputs = {
            "input_ids": torch.tensor([[1, 2, 3]]),
            "attention_mask": torch.tensor([[1, 1, 1]]),
        }
        mock_tokenizer.return_value = mock_inputs

        mock_outputs = MagicMock()
        mock_outputs.last_hidden_state = torch.randn(1, 3, embedder.dimensions)
        mock_model.return_value = mock_outputs

        embedder.embed_chunks(chunks)

        call_args = mock_tokenizer.call_args
        expected_prefix = JINA_TASK_PREFIXES["code2code"]["passage"]
        passed_texts = call_args[0][0] if call_args[0] else call_args[1].get("texts", [])
        assert passed_texts[0].startswith(expected_prefix)


class TestHuggingFaceEmbedderEmbedQuery:
    @patch("src.embedder.AutoTokenizer")
    @patch("src.embedder.AutoModel")
    def test_embed_query_returns_vector(self, mock_model_class, mock_tokenizer_class):
        mock_tokenizer = MagicMock()
        mock_model = MagicMock()
        mock_tokenizer_class.from_pretrained.return_value = mock_tokenizer
        mock_model_class.from_pretrained.return_value = mock_model

        embedder = HuggingFaceEmbedder()

        mock_inputs = {
            "input_ids": torch.tensor([[1, 2, 3]]),
            "attention_mask": torch.tensor([[1, 1, 1]]),
        }
        mock_tokenizer.return_value = mock_inputs

        mock_outputs = MagicMock()
        mock_outputs.last_hidden_state = torch.randn(1, 3, embedder.dimensions)
        mock_model.return_value = mock_outputs

        result = embedder.embed_query("test query")

        assert isinstance(result, list)
        assert len(result) == embedder.dimensions


class TestHuggingFaceEmbedderDimensions:
    @patch("src.embedder.AutoTokenizer")
    @patch("src.embedder.AutoModel")
    def test_get_dimensions_default(self, mock_model_class, mock_tokenizer_class):
        mock_tokenizer = MagicMock()
        mock_model = MagicMock()
        mock_tokenizer_class.from_pretrained.return_value = mock_tokenizer
        mock_model_class.from_pretrained.return_value = mock_model

        embedder = HuggingFaceEmbedder()
        assert embedder.get_dimensions() == MODEL_CONFIGS[DEFAULT_MODEL_ID]["dimensions"]

    @patch("src.embedder.AutoTokenizer")
    @patch("src.embedder.AutoModel")
    def test_get_dimensions_jina(self, mock_model_class, mock_tokenizer_class):
        mock_tokenizer = MagicMock()
        mock_model = MagicMock()
        mock_tokenizer_class.from_pretrained.return_value = mock_tokenizer
        mock_model_class.from_pretrained.return_value = mock_model

        embedder = HuggingFaceEmbedder(model_id="jina")
        assert embedder.get_dimensions() == 1536

    @patch("src.embedder.AutoTokenizer")
    @patch("src.embedder.AutoModel")
    def test_get_dimensions_nomic(self, mock_model_class, mock_tokenizer_class):
        mock_tokenizer = MagicMock()
        mock_model = MagicMock()
        mock_tokenizer_class.from_pretrained.return_value = mock_tokenizer
        mock_model_class.from_pretrained.return_value = mock_model

        embedder = HuggingFaceEmbedder(model_id="nomic")
        assert embedder.get_dimensions() == 3584


class TestHuggingFaceEmbedderHealthCheck:
    @patch("src.embedder.AutoTokenizer")
    @patch("src.embedder.AutoModel")
    def test_health_check_success(self, mock_model_class, mock_tokenizer_class):
        mock_tokenizer = MagicMock()
        mock_model = MagicMock()
        mock_tokenizer_class.from_pretrained.return_value = mock_tokenizer
        mock_model_class.from_pretrained.return_value = mock_model

        embedder = HuggingFaceEmbedder()
        result = embedder.check_health()

        assert result is True

    @patch("src.embedder.AutoTokenizer")
    @patch("src.embedder.AutoModel")
    def test_health_check_failure(self, mock_model_class, mock_tokenizer_class):
        mock_tokenizer = MagicMock()
        mock_model = MagicMock()
        mock_tokenizer_class.from_pretrained.return_value = mock_tokenizer
        mock_model_class.from_pretrained.return_value = mock_model

        embedder = HuggingFaceEmbedder()
        delattr(embedder, "model")
        result = embedder.check_health()

        assert result is False


class TestCreateEmbedder:
    @patch("src.embedder.AutoTokenizer")
    @patch("src.embedder.AutoModel")
    def test_factory_returns_huggingface_embedder(self, mock_model, mock_tokenizer):
        embedder = create_embedder()
        assert isinstance(embedder, HuggingFaceEmbedder)

    @patch("src.embedder.AutoTokenizer")
    @patch("src.embedder.AutoModel")
    def test_factory_with_model_id(self, mock_model, mock_tokenizer):
        embedder = create_embedder(model_id="jina")
        assert embedder.model_id == "jina"
        assert embedder.model_name == "jinaai/jina-code-embeddings-1.5b"

    @patch("src.embedder.AutoTokenizer")
    @patch("src.embedder.AutoModel")
    def test_factory_passes_kwargs(self, mock_model, mock_tokenizer):
        embedder = create_embedder(device="cuda")
        assert embedder.device == "cuda"