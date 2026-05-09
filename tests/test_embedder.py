"""Tests for the embedder module."""

from unittest.mock import MagicMock, patch

import pytest
import torch

from src.embedder import HuggingFaceEmbedder, create_embedder, JINA_TASK_PREFIXES


class TestHuggingFaceEmbedderInit:
    @patch("src.embedder.AutoTokenizer")
    @patch("src.embedder.AutoModel")
    def test_init_with_defaults(self, mock_model_class, mock_tokenizer_class):
        mock_tokenizer = MagicMock()
        mock_model = MagicMock()
        mock_tokenizer_class.from_pretrained.return_value = mock_tokenizer
        mock_model_class.from_pretrained.return_value = mock_model

        embedder = HuggingFaceEmbedder()

        assert embedder.model_name == "jinaai/jina-code-embeddings-1.5b"
        assert embedder.device == "cpu"
        mock_model.eval.assert_called_once()

    @patch("src.embedder.AutoTokenizer")
    @patch("src.embedder.AutoModel")
    def test_init_with_custom_params(self, mock_model_class, mock_tokenizer_class):
        mock_tokenizer = MagicMock()
        mock_model = MagicMock()
        mock_tokenizer_class.from_pretrained.return_value = mock_tokenizer
        mock_model_class.from_pretrained.return_value = mock_model

        embedder = HuggingFaceEmbedder(model="custom-model", device="cuda")

        assert embedder.model_name == "custom-model"
        assert embedder.device == "cuda"


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
            output.last_hidden_state = torch.randn(batch_size, 10, 1536)
            return output

        mock_model.side_effect = mock_forward

        result = embedder.embed_chunks(chunks)

        assert len(result) == 2
        assert "embedding" in result[0]
        assert "embedding" in result[1]
        assert len(result[0]["embedding"]) == 1536
        assert len(result[1]["embedding"]) == 1536

    @patch("src.embedder.AutoTokenizer")
    @patch("src.embedder.AutoModel")
    def test_embed_chunks_prepends_passage_prefix(self, mock_model_class, mock_tokenizer_class):
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
        mock_outputs.last_hidden_state = torch.randn(1, 3, 1536)
        mock_model.return_value = mock_outputs

        embedder.embed_chunks(chunks)

        call_args = mock_tokenizer.call_args
        expected_prefix = JINA_TASK_PREFIXES["code2code"]["passage"]
        passed_texts = call_args[0][0] if call_args[0] else call_args[1].get("texts", [])
        assert passed_texts[0].startswith(expected_prefix)

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
    def test_embed_chunks_preserves_original_chunks(self, mock_model_class, mock_tokenizer_class):
        mock_tokenizer = MagicMock()
        mock_model = MagicMock()
        mock_tokenizer_class.from_pretrained.return_value = mock_tokenizer
        mock_model_class.from_pretrained.return_value = mock_model

        embedder = HuggingFaceEmbedder()
        chunks = [{"text": "chunk1"}]

        mock_inputs = {
            "input_ids": torch.tensor([[1, 2, 3]]),
            "attention_mask": torch.tensor([[1, 1, 1]]),
        }
        mock_tokenizer.return_value = mock_inputs

        mock_outputs = MagicMock()
        mock_outputs.last_hidden_state = torch.randn(1, 3, 1536)
        mock_model.return_value = mock_outputs

        result = embedder.embed_chunks(chunks)

        assert "embedding" in result[0]
        assert "embedding" not in chunks[0]


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
        mock_outputs.last_hidden_state = torch.randn(1, 3, 1536)
        mock_model.return_value = mock_outputs

        result = embedder.embed_query("test query")

        assert isinstance(result, list)
        assert len(result) == 1536

    @patch("src.embedder.AutoTokenizer")
    @patch("src.embedder.AutoModel")
    def test_embed_query_prepends_query_prefix(self, mock_model_class, mock_tokenizer_class):
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
        mock_outputs.last_hidden_state = torch.randn(1, 3, 1536)
        mock_model.return_value = mock_outputs

        test_query = "find a function that sorts arrays"
        embedder.embed_query(test_query)

        call_args = mock_tokenizer.call_args
        expected_prefix = JINA_TASK_PREFIXES["nl2code"]["query"]
        passed_text = call_args[0][0] if call_args[0] else call_args[1].get("text", "")
        assert passed_text.startswith(expected_prefix)


class TestHuggingFaceEmbedderDimensions:
    @patch("src.embedder.AutoTokenizer")
    @patch("src.embedder.AutoModel")
    def test_get_dimensions_returns_1536(self, mock_model_class, mock_tokenizer_class):
        mock_tokenizer = MagicMock()
        mock_model = MagicMock()
        mock_tokenizer_class.from_pretrained.return_value = mock_tokenizer
        mock_model_class.from_pretrained.return_value = mock_model

        embedder = HuggingFaceEmbedder()
        assert embedder.get_dimensions() == 1536


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
    def test_factory_passes_kwargs(self, mock_model, mock_tokenizer):
        embedder = create_embedder(model="custom-model", device="cuda")
        assert embedder.model_name == "custom-model"
        assert embedder.device == "cuda"
