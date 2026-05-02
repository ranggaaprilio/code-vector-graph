"""Tests for the embedder module."""

import logging
from unittest.mock import MagicMock, patch

import pytest
import requests
import torch

from src.config import DEFAULT_MODEL, DEFAULT_OLLAMA_URL, EMBEDDING_PREFIX
from src.embedder import OllamaEmbedder, HuggingFaceEmbedder, create_embedder


class TestOllamaEmbedderInit:
    """Test OllamaEmbedder initialization."""

    @patch("src.embedder.OllamaEmbeddings")
    def test_init_with_defaults(self, mock_embeddings_class):
        """Test initialization with default parameters."""
        mock_embeddings = MagicMock()
        mock_embeddings_class.return_value = mock_embeddings

        embedder = OllamaEmbedder()

        assert embedder.model == DEFAULT_MODEL
        assert embedder.base_url == DEFAULT_OLLAMA_URL
        mock_embeddings_class.assert_called_once_with(
            model=DEFAULT_MODEL,
            base_url=DEFAULT_OLLAMA_URL,
        )

    @patch("src.embedder.OllamaEmbeddings")
    def test_init_with_custom_params(self, mock_embeddings_class):
        """Test initialization with custom parameters."""
        mock_embeddings = MagicMock()
        mock_embeddings_class.return_value = mock_embeddings

        custom_model = "custom-model:latest"
        custom_url = "http://custom:11434"

        embedder = OllamaEmbedder(model=custom_model, base_url=custom_url)

        assert embedder.model == custom_model
        assert embedder.base_url == custom_url
        mock_embeddings_class.assert_called_once_with(
            model=custom_model,
            base_url=custom_url,
        )


class TestOllamaEmbedderHealthCheck:
    """Test OllamaEmbedder health check functionality."""

    @patch("src.embedder.OllamaEmbeddings")
    @patch("src.embedder.requests.get")
    def test_health_check_success(self, mock_get, mock_embeddings_class):
        """Test health check when Ollama is reachable and model is available."""
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "models": [{"name": DEFAULT_MODEL}]
        }
        mock_get.return_value = mock_response

        embedder = OllamaEmbedder()
        result = embedder.check_health()

        assert result is True
        mock_get.assert_called_once_with(
            f"{DEFAULT_OLLAMA_URL}/api/tags",
            timeout=5,
        )

    @patch("src.embedder.OllamaEmbeddings")
    @patch("src.embedder.requests.get")
    def test_health_check_model_variant(self, mock_get, mock_embeddings_class):
        """Test health check when model variant exists (without :latest)."""
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "models": [{"name": "nomic-embed-text:v1.5"}]
        }
        mock_get.return_value = mock_response

        embedder = OllamaEmbedder()
        result = embedder.check_health()

        assert result is True

    @patch("src.embedder.OllamaEmbeddings")
    @patch("src.embedder.requests.get")
    def test_health_check_model_not_found(self, mock_get, mock_embeddings_class):
        """Test health check when model is not available."""
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "models": [{"name": "other-model:latest"}]
        }
        mock_get.return_value = mock_response

        embedder = OllamaEmbedder()
        result = embedder.check_health()

        assert result is False

    @patch("src.embedder.OllamaEmbeddings")
    @patch("src.embedder.requests.get")
    def test_health_check_connection_error(self, mock_get, mock_embeddings_class):
        """Test health check when Ollama is not reachable."""
        mock_get.side_effect = requests.exceptions.ConnectionError()

        embedder = OllamaEmbedder()
        result = embedder.check_health()

        assert result is False

    @patch("src.embedder.OllamaEmbeddings")
    @patch("src.embedder.requests.get")
    def test_health_check_timeout(self, mock_get, mock_embeddings_class):
        """Test health check when request times out."""
        mock_get.side_effect = requests.exceptions.Timeout()

        embedder = OllamaEmbedder()
        result = embedder.check_health()

        assert result is False


class TestOllamaEmbedderEmbedChunks:
    """Test OllamaEmbedder chunk embedding functionality."""

    @patch("src.embedder.OllamaEmbeddings")
    def test_embed_chunks_with_prefix(self, mock_embeddings_class):
        """Test that search_document: prefix is prepended to chunk text."""
        mock_embeddings = MagicMock()
        mock_embeddings.embed_documents.return_value = [[0.1] * 768, [0.2] * 768]
        mock_embeddings_class.return_value = mock_embeddings

        embedder = OllamaEmbedder()
        chunks = [
            {"text": "def foo(): pass"},
            {"text": "class Bar: pass"},
        ]

        result = embedder.embed_chunks(chunks)

        assert len(result) == 2
        mock_embeddings.embed_documents.assert_called_once()
        call_args = mock_embeddings.embed_documents.call_args[0][0]
        assert call_args[0] == f"{EMBEDDING_PREFIX}def foo(): pass"
        assert call_args[1] == f"{EMBEDDING_PREFIX}class Bar: pass"

    @patch("src.embedder.OllamaEmbeddings")
    def test_embed_chunks_adds_embedding_field(self, mock_embeddings_class):
        """Test that embedding field is added to each chunk."""
        mock_embeddings = MagicMock()
        mock_embeddings.embed_documents.return_value = [[0.1] * 768, [0.2] * 768]
        mock_embeddings_class.return_value = mock_embeddings

        embedder = OllamaEmbedder()
        chunks = [
            {"text": "chunk1", "metadata": {"key": "value"}},
            {"text": "chunk2"},
        ]

        result = embedder.embed_chunks(chunks)

        assert "embedding" in result[0]
        assert "embedding" in result[1]
        assert result[0]["embedding"] == [0.1] * 768
        assert result[1]["embedding"] == [0.2] * 768
        assert result[0]["metadata"] == {"key": "value"}

    @patch("src.embedder.OllamaEmbeddings")
    def test_embed_chunks_empty_list(self, mock_embeddings_class):
        """Test embedding empty list returns empty list."""
        mock_embeddings = MagicMock()
        mock_embeddings_class.return_value = mock_embeddings

        embedder = OllamaEmbedder()
        result = embedder.embed_chunks([])

        assert result == []
        mock_embeddings.embed_documents.assert_not_called()

    @patch("src.embedder.OllamaEmbeddings")
    def test_embed_chunks_batch_processing(self, mock_embeddings_class):
        """Test that chunks are processed in batches."""
        mock_embeddings = MagicMock()
        mock_embeddings.embed_documents.side_effect = [
            [[0.1] * 768, [0.2] * 768],
            [[0.3] * 768],
        ]
        mock_embeddings_class.return_value = mock_embeddings

        embedder = OllamaEmbedder()
        chunks = [
            {"text": "chunk1"},
            {"text": "chunk2"},
            {"text": "chunk3"},
        ]

        result = embedder.embed_chunks(chunks, batch_size=2)

        assert len(result) == 3
        assert mock_embeddings.embed_documents.call_count == 2

    @patch("src.embedder.OllamaEmbeddings")
    def test_embed_chunks_preserves_original_chunks(self, mock_embeddings_class):
        """Test that original chunks are not modified (copy is made)."""
        mock_embeddings = MagicMock()
        mock_embeddings.embed_documents.return_value = [[0.1] * 768]
        mock_embeddings_class.return_value = mock_embeddings

        embedder = OllamaEmbedder()
        chunks = [{"text": "chunk1"}]

        result = embedder.embed_chunks(chunks)

        assert "embedding" in result[0]
        assert "embedding" not in chunks[0]


class TestOllamaEmbedderEmbedQuery:
    """Test OllamaEmbedder query embedding functionality."""

    @patch("src.embedder.OllamaEmbeddings")
    def test_embed_query_with_prefix(self, mock_embeddings_class):
        """Test that search_query: prefix is prepended to query."""
        mock_embeddings = MagicMock()
        mock_embeddings.embed_query.return_value = [0.5] * 768
        mock_embeddings_class.return_value = mock_embeddings

        embedder = OllamaEmbedder()
        query = "how to implement authentication"

        result = embedder.embed_query(query)

        assert result == [0.5] * 768
        mock_embeddings.embed_query.assert_called_once_with(
            f"search_query: {query}"
        )

    @patch("src.embedder.OllamaEmbeddings")
    def test_embed_query_returns_vector(self, mock_embeddings_class):
        """Test that embed_query returns the embedding vector."""
        expected_embedding = [0.1] * 768
        mock_embeddings = MagicMock()
        mock_embeddings.embed_query.return_value = expected_embedding
        mock_embeddings_class.return_value = mock_embeddings

        embedder = OllamaEmbedder()
        result = embedder.embed_query("test query")

        assert result == expected_embedding
        assert len(result) == 768


class TestOllamaEmbedderDimensions:
    """Test OllamaEmbedder dimensions."""

    @patch("src.embedder.OllamaEmbeddings")
    def test_get_dimensions_returns_768(self, mock_embeddings_class):
        """Test that Ollama returns 768 dimensions."""
        mock_embeddings_class.return_value = MagicMock()
        embedder = OllamaEmbedder()
        assert embedder.get_dimensions() == 768


class TestHuggingFaceEmbedderInit:
    """Test HuggingFaceEmbedder initialization."""

    @patch("src.embedder.AutoTokenizer")
    @patch("src.embedder.AutoModel")
    def test_init_with_defaults(self, mock_model_class, mock_tokenizer_class):
        """Test HuggingFaceEmbedder initialization with defaults."""
        mock_tokenizer = MagicMock()
        mock_model = MagicMock()
        mock_tokenizer_class.from_pretrained.return_value = mock_tokenizer
        mock_model_class.from_pretrained.return_value = mock_model

        embedder = HuggingFaceEmbedder()

        assert embedder.model_name == "Salesforce/codet5p-110m-embedding"
        assert embedder.device == "cpu"
        mock_tokenizer_class.from_pretrained.assert_called_once_with(
            "Salesforce/codet5p-110m-embedding", trust_remote_code=True
        )
        mock_model_class.from_pretrained.assert_called_once_with(
            "Salesforce/codet5p-110m-embedding", trust_remote_code=True
        )
        mock_model.eval.assert_called_once()

    @patch("src.embedder.AutoTokenizer")
    @patch("src.embedder.AutoModel")
    def test_init_with_custom_params(self, mock_model_class, mock_tokenizer_class):
        """Test HuggingFaceEmbedder initialization with custom parameters."""
        mock_tokenizer = MagicMock()
        mock_model = MagicMock()
        mock_tokenizer_class.from_pretrained.return_value = mock_tokenizer
        mock_model_class.from_pretrained.return_value = mock_model

        embedder = HuggingFaceEmbedder(
            model="custom-model",
            device="cuda"
        )

        assert embedder.model_name == "custom-model"
        assert embedder.device == "cuda"
        mock_tokenizer_class.from_pretrained.assert_called_once_with(
            "custom-model", trust_remote_code=True
        )
        mock_model_class.from_pretrained.assert_called_once_with(
            "custom-model", trust_remote_code=True
        )


class TestHuggingFaceEmbedderEmbedChunks:
    """Test HuggingFaceEmbedder chunk embedding functionality."""

    @patch("src.embedder.AutoTokenizer")
    @patch("src.embedder.AutoModel")
    def test_embed_chunks_returns_embeddings(self, mock_model_class, mock_tokenizer_class):
        """Test that embed_chunks returns chunks with embedding field."""
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
            return (torch.randn(batch_size, 10, 256),)

        mock_model.side_effect = mock_forward

        result = embedder.embed_chunks(chunks)

        assert len(result) == 2
        assert "embedding" in result[0]
        assert "embedding" in result[1]
        assert len(result[0]["embedding"]) == 256
        assert len(result[1]["embedding"]) == 256

    @patch("src.embedder.AutoTokenizer")
    @patch("src.embedder.AutoModel")
    def test_embed_chunks_no_prefix(self, mock_model_class, mock_tokenizer_class):
        """Test that HuggingFace doesn't add prefixes (unlike Ollama)."""
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

        mock_outputs = (torch.randn(1, 3, 256),)
        mock_model.return_value = mock_outputs

        embedder.embed_chunks(chunks)

        call_args = mock_tokenizer.call_args
        assert "search_document" not in str(call_args)

    @patch("src.embedder.AutoTokenizer")
    @patch("src.embedder.AutoModel")
    def test_embed_chunks_empty_list(self, mock_model_class, mock_tokenizer_class):
        """Test embedding empty list returns empty list."""
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
        """Test that original chunks are not modified (copy is made)."""
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

        mock_outputs = (torch.randn(1, 3, 256),)
        mock_model.return_value = mock_outputs

        result = embedder.embed_chunks(chunks)

        assert "embedding" in result[0]
        assert "embedding" not in chunks[0]


class TestHuggingFaceEmbedderEmbedQuery:
    """Test HuggingFaceEmbedder query embedding functionality."""

    @patch("src.embedder.AutoTokenizer")
    @patch("src.embedder.AutoModel")
    def test_embed_query_returns_vector(self, mock_model_class, mock_tokenizer_class):
        """Test that embed_query returns the embedding vector."""
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

        mock_outputs = (torch.randn(1, 3, 256),)
        mock_model.return_value = mock_outputs

        result = embedder.embed_query("test query")

        assert isinstance(result, list)
        assert len(result) == 256


class TestHuggingFaceEmbedderDimensions:
    """Test HuggingFaceEmbedder dimensions."""

    @patch("src.embedder.AutoTokenizer")
    @patch("src.embedder.AutoModel")
    def test_get_dimensions_returns_256(self, mock_model_class, mock_tokenizer_class):
        """Test that HuggingFace returns 256 dimensions."""
        mock_tokenizer = MagicMock()
        mock_model = MagicMock()
        mock_tokenizer_class.from_pretrained.return_value = mock_tokenizer
        mock_model_class.from_pretrained.return_value = mock_model

        embedder = HuggingFaceEmbedder()
        assert embedder.get_dimensions() == 256


class TestHuggingFaceEmbedderHealthCheck:
    """Test HuggingFaceEmbedder health check functionality."""

    @patch("src.embedder.AutoTokenizer")
    @patch("src.embedder.AutoModel")
    def test_health_check_success(self, mock_model_class, mock_tokenizer_class):
        """Test health check when model and tokenizer are loaded."""
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
        """Test health check when model is not loaded."""
        mock_tokenizer = MagicMock()
        mock_model = MagicMock()
        mock_tokenizer_class.from_pretrained.return_value = mock_tokenizer
        mock_model_class.from_pretrained.return_value = mock_model

        embedder = HuggingFaceEmbedder()
        delattr(embedder, "model")
        result = embedder.check_health()

        assert result is False


class TestCreateEmbedder:
    """Test factory function for creating embedders."""

    @patch("src.embedder.OllamaEmbeddings")
    def test_factory_returns_ollama_embedder(self, mock_ollama):
        """Test factory creates OllamaEmbedder for 'ollama' provider."""
        embedder = create_embedder("ollama")
        assert isinstance(embedder, OllamaEmbedder)

    @patch("src.embedder.AutoTokenizer")
    @patch("src.embedder.AutoModel")
    def test_factory_returns_huggingface_embedder(self, mock_model, mock_tokenizer):
        """Test factory creates HuggingFaceEmbedder for 'huggingface' provider."""
        embedder = create_embedder("huggingface")
        assert isinstance(embedder, HuggingFaceEmbedder)

    def test_factory_raises_on_unknown_provider(self):
        """Test factory raises ValueError for unknown provider."""
        with pytest.raises(ValueError, match="Unknown provider"):
            create_embedder("unknown")

    @patch("src.embedder.OllamaEmbeddings")
    def test_factory_passes_kwargs_to_ollama(self, mock_ollama):
        """Test factory passes kwargs to OllamaEmbedder."""
        embedder = create_embedder("ollama", model="custom-model", base_url="http://custom:11434")
        assert embedder.model == "custom-model"
        assert embedder.base_url == "http://custom:11434"

    @patch("src.embedder.AutoTokenizer")
    @patch("src.embedder.AutoModel")
    def test_factory_passes_kwargs_to_huggingface(self, mock_model, mock_tokenizer):
        """Test factory passes kwargs to HuggingFaceEmbedder."""
        embedder = create_embedder("huggingface", model="custom-model", device="cuda")
        assert embedder.model_name == "custom-model"
        assert embedder.device == "cuda"
