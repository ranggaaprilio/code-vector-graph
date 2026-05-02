"""Embedder module for generating embeddings using Ollama."""

import copy
import logging
import sys
from abc import ABC, abstractmethod
from typing import Any, List

import requests
import torch
from langchain_ollama import OllamaEmbeddings
from transformers import AutoConfig, AutoModel, AutoTokenizer

from .config import (
    DEFAULT_MODEL,
    DEFAULT_OLLAMA_URL,
    EMBEDDING_DIMENSIONS,
    EMBEDDING_PREFIX,
    EMBEDDING_PROVIDERS,
)

logger = logging.getLogger(__name__)


class Embedder(ABC):
    """Abstract base class for embedding providers."""

    @abstractmethod
    def embed_chunks(self, chunks: list[dict], batch_size: int = 64) -> list[dict]:
        """Embed a list of code chunks.

        Args:
            chunks: List of chunk dictionaries with 'text' field
            batch_size: Number of chunks to embed per batch

        Returns:
            List of chunks with 'embedding' field added
        """
        pass

    @abstractmethod
    def embed_query(self, query: str) -> list[float]:
        """Embed a single query string.

        Args:
            query: The query string to embed

        Returns:
            Embedding vector
        """
        pass

    @abstractmethod
    def check_health(self) -> bool:
        """Check if the embedding service is reachable and healthy.

        Returns:
            True if the service is available, False otherwise
        """
        pass

    @abstractmethod
    def get_dimensions(self) -> int:
        """Get the dimensionality of the embedding vectors.

        Returns:
            Number of dimensions in the embedding vectors
        """
        pass


class OllamaEmbedder(Embedder):
    """Ollama embedding implementation."""

    def __init__(
        self,
        model: str = DEFAULT_MODEL,
        base_url: str = DEFAULT_OLLAMA_URL,
    ):
        """Initialize the Ollama embedder.

        Args:
            model: The Ollama model to use for embeddings
            base_url: The base URL for the Ollama API
        """
        self.model = model
        self.base_url = base_url
        self.embeddings = OllamaEmbeddings(
            model=model,
            base_url=base_url,
        )
        logger.debug(
            f"Initialized OllamaEmbedder with model={model}, base_url={base_url}"
        )

    def embed_chunks(self, chunks: list[dict], batch_size: int = 64) -> list[dict]:
        """Embed a list of code chunks with search_document prefix.

        Args:
            chunks: List of chunk dictionaries with 'text' field
            batch_size: Number of chunks to embed per batch

        Returns:
            List of chunks with 'embedding' field added (768-dim vector)
        """
        if not chunks:
            return []

        prefix = EMBEDDING_PROVIDERS["ollama"]["prefix"]
        total_batches = (len(chunks) + batch_size - 1) // batch_size
        result_chunks = []

        for batch_idx in range(total_batches):
            start_idx = batch_idx * batch_size
            end_idx = min(start_idx + batch_size, len(chunks))
            batch = chunks[start_idx:end_idx]

            logger.info(f"Embedding batch {batch_idx + 1}/{total_batches}...")

            texts = [f"{prefix}{chunk['text']}" for chunk in batch]
            embeddings = self.embeddings.embed_documents(texts)

            for chunk, embedding in zip(batch, embeddings):
                chunk_with_embedding = chunk.copy()
                chunk_with_embedding["embedding"] = embedding
                result_chunks.append(chunk_with_embedding)

            logger.debug(f"Embedded batch {batch_idx + 1}: {len(batch)} chunks")

        logger.info(f"Successfully embedded {len(result_chunks)} chunks")
        return result_chunks

    def embed_query(self, query: str) -> list[float]:
        """Embed a single query string with search_query prefix.

        Args:
            query: The query string to embed

        Returns:
            768-dimensional embedding vector
        """
        query_prefix = EMBEDDING_PROVIDERS["ollama"]["query_prefix"]
        prefixed_query = f"{query_prefix}{query}"
        embedding = self.embeddings.embed_query(prefixed_query)
        logger.debug(f"Embedded query: '{query[:50]}...' (truncated)")
        return embedding

    def check_health(self) -> bool:
        """Check if Ollama is reachable and the model is available.

        Returns:
            True if Ollama is reachable and model is available, False otherwise
        """
        try:
            response = requests.get(f"{self.base_url}/api/tags", timeout=5)
            response.raise_for_status()

            data = response.json()
            models = [m.get("name", "") for m in data.get("models", [])]

            if self.model in models:
                logger.debug(f"Health check passed: model {self.model} is available")
                return True
            else:
                model_base = self.model.split(":")[0]
                available_models = [m for m in models if model_base in m]
                if available_models:
                    logger.debug(
                        f"Health check passed: found model variants {available_models}"
                    )
                    return True
                logger.error(
                    f"Model {self.model} not found in available models: {models}"
                )
                return False

        except requests.exceptions.ConnectionError:
            logger.error(f"Cannot connect to Ollama at {self.base_url}")
            return False
        except requests.exceptions.Timeout:
            logger.error(f"Timeout connecting to Ollama at {self.base_url}")
            return False
        except requests.exceptions.RequestException as e:
            logger.error(f"Health check failed: {e}")
            return False

    def get_dimensions(self) -> int:
        """Get embedding dimensions for Ollama provider."""
        return EMBEDDING_PROVIDERS["ollama"]["dimensions"]


class HuggingFaceEmbedder(Embedder):
    """HuggingFace embedding implementation using transformers AutoModel/AutoTokenizer."""

    def __init__(self, model: str | None = None, device: str | None = None):
        """Initialize the HuggingFace embedder.

        - model defaults to EMBEDDING_PROVIDERS["huggingface"]["model"]
        - device defaults to 'cpu' (CPU-only as per requirements)
        """
        self.model_name = model or EMBEDDING_PROVIDERS["huggingface"]["model"]
        self.device = device or "cpu"

        # Load tokenizer and model with trust_remote_code=True as required
        logger.info(f"Loading HuggingFace model {self.model_name}...")
        try:
            self.tokenizer = AutoTokenizer.from_pretrained(
                self.model_name, trust_remote_code=True, local_files_only=True
            )
            # Try loading with AutoModel first
            try:
                self.model = AutoModel.from_pretrained(
                    self.model_name, trust_remote_code=True, local_files_only=True
                )
            except AttributeError as ae:
                # Handle missing 'is_decoder' attribute in some model configs
                if "is_decoder" in str(ae) or "is_encoder_decoder" in str(ae):
                    logger.warning(
                        f"AutoModel failed with config error, trying config patch: {ae}"
                    )
                    # Load config, patch it, then load model
                    config = AutoConfig.from_pretrained(
                        self.model_name, trust_remote_code=True, local_files_only=True
                    )
                    original_init = config.__class__.__init__

                    def patched_init(self, *args, **kwargs):
                        original_init(self, *args, **kwargs)
                        self.is_decoder = False
                        self.is_encoder_decoder = False

                    config.__class__.__init__ = patched_init
                    config.is_decoder = False
                    config.is_encoder_decoder = False
                    if hasattr(config, "decoder") and config.decoder is not None:
                        config.decoder.is_decoder = False
                    try:
                        self.model = AutoModel.from_pretrained(
                            self.model_name,
                            config=config,
                            trust_remote_code=True,
                            local_files_only=True,
                        )
                        logger.info("Successfully loaded model with config patch")
                    except AttributeError as ae2:
                        logger.error(f"Config patch failed: {ae2}")
                        raise RuntimeError(
                            f"Failed to load {self.model_name} even with config patch. "
                            f"The model may be incompatible with your transformers version. "
                            f"Try using --embedding-provider ollama instead."
                        ) from ae2
                else:
                    raise
        except Exception as e:
            logger.error(f"Failed to load HuggingFace model '{self.model_name}': {e}")
            print(
                f"\nERROR: Failed to load model '{self.model_name}'.",
                file=sys.stderr,
            )
            print(
                f"Details: {e}",
                file=sys.stderr,
            )
            print(
                "\nPlease ensure the model files are downloaded correctly:",
                file=sys.stderr,
            )
            print(
                f'  python -c "from transformers import AutoModel, AutoTokenizer; '
                f"AutoTokenizer.from_pretrained('{self.model_name}', trust_remote_code=True); "
                f"AutoModel.from_pretrained('{self.model_name}', trust_remote_code=True)\"",
                file=sys.stderr,
            )
            print(
                f"\nOr switch to Ollama provider: --embedding-provider ollama",
                file=sys.stderr,
            )
            raise
        # Ensure the model is in evaluation mode
        self.model.eval()
        # Move to device if possible
        try:
            self.model.to(self.device)
        except Exception:
            # If device can't be set (e.g., CPU-only environments without proper config), continue anyway
            pass

        logger.debug(
            f"Initialized HuggingFaceEmbedder with model={self.model_name}, device={self.device}"
        )

    def _token_truncation_warnings(self, texts: List[str]) -> int:
        """Return number of texts longer than 512 tokens (approximation).

        This uses a best-effort approach by encoding each text and counting tokens.
        """
        count = 0
        for t in texts:
            try:
                tokens = self.tokenizer.encode(t)
                if len(tokens) > 512:
                    count += 1
            except Exception:
                # If tokenization fails for any text, skip counting
                continue
        return count

    def embed_chunks(self, chunks: list[dict], batch_size: int = 64) -> list[dict]:
        """Embed a list of code chunks using the HuggingFace model.

        - No prefix is added to the chunk text (unlike Ollama version)
        - Texts are tokenized with max_length=512 and truncation
        - Embeddings are mean-pooled over tokens and L2-normalized
        - Returns new list with an 'embedding' field per chunk (256-dim)
        """
        if not chunks:
            return []

        texts = []
        for ch in chunks:
            if isinstance(ch, dict) and "text" in ch:
                texts.append(ch["text"])
            else:
                texts.append(str(ch))

        # Log any potential truncations
        truncated_count = self._token_truncation_warnings(texts)
        if truncated_count:
            logger.warning(
                f"Warning: {truncated_count} chunks exceeded 512 tokens and were truncated"
            )

        total = len(texts)
        result_chunks: List[dict] = []
        total_batches = (total + batch_size - 1) // batch_size
        with torch.no_grad():
            for batch_idx in range(total_batches):
                start = batch_idx * batch_size
                end = min(start + batch_size, total)
                batch_texts = texts[start:end]

                # Tokenize with truncation to 512 tokens
                inputs = self.tokenizer(
                    batch_texts,
                    padding=True,
                    truncation=True,
                    max_length=512,
                    return_tensors="pt",
                )
                # Move to device if necessary
                for k, v in inputs.items():
                    if isinstance(v, torch.Tensor):
                        inputs[k] = v.to(self.device)

                outputs = self.model(**inputs)
                # Transformer models return (last_hidden_state, pooler_output, ...)
                last_hidden = outputs[0]  # shape: (batch, seq_len, hidden)

                # Mean pooling with attention mask to ignore padding
                attention_mask = inputs.get("attention_mask")
                if attention_mask is not None:
                    # Expand mask to match hidden state dimensions: (batch, seq_len) -> (batch, seq_len, hidden)
                    mask = (
                        attention_mask.unsqueeze(-1)
                        .expand(-1, -1, last_hidden.size(-1))
                        .float()
                    )
                    sum_embeddings = torch.sum(last_hidden * mask, dim=1)
                    sum_mask = mask.sum(dim=1)
                    mean_pooled = sum_embeddings / sum_mask.clamp(min=1e-9)
                else:
                    mean_pooled = last_hidden.mean(dim=1)

                # L2 normalize
                embeddings = torch.nn.functional.normalize(mean_pooled, p=2, dim=1)

                # Move back to CPU and convert to Python lists
                embeddings_list = embeddings.cpu().tolist()

                for i, emb in enumerate(embeddings_list):
                    idx = start + i
                    orig = chunks[idx]
                    chunk = (
                        orig.copy()
                        if isinstance(orig, dict)
                        else {"text": batch_texts[i]}
                    )
                    chunk["embedding"] = emb
                    result_chunks.append(chunk)

        return result_chunks

    def embed_query(self, query: str) -> list[float]:
        """Embed a single query string using the HuggingFace model.

        Returns a 256-dim embedding vector.
        """
        # Tokenize single input text
        inputs = self.tokenizer(
            query,
            padding=True,
            truncation=True,
            max_length=512,
            return_tensors="pt",
        )
        for k, v in inputs.items():
            if isinstance(v, torch.Tensor):
                inputs[k] = v.to(self.device)
        with torch.no_grad():
            outputs = self.model(**inputs)
            last_hidden = outputs[0]
            mean_pooled = last_hidden.mean(dim=1)
            embedding = torch.nn.functional.normalize(mean_pooled, p=2, dim=1)
            vec = embedding.cpu().squeeze(0).tolist()
        return vec

    def check_health(self) -> bool:
        """Simple health check: ensure model and tokenizer are loaded."""
        try:
            return (
                hasattr(self, "model")
                and hasattr(self, "tokenizer")
                and self.model is not None
                and self.tokenizer is not None
            )
        except Exception:
            return False

    def get_dimensions(self) -> int:
        """Get embedding dimensions for HuggingFace provider."""
        return EMBEDDING_PROVIDERS["huggingface"]["dimensions"]


def create_embedder(provider: str, **kwargs) -> Embedder:
    """Factory function to create appropriate embedder.

    Args:
        provider: The provider name ('ollama' or 'huggingface')
        **kwargs: Additional arguments passed to the embedder constructor

    Returns:
        An instance of the appropriate Embedder subclass

    Raises:
        ValueError: If the provider is not recognized
    """
    if provider == "ollama":
        return OllamaEmbedder(**kwargs)
    elif provider == "huggingface":
        return HuggingFaceEmbedder(**kwargs)
    else:
        raise ValueError(f"Unknown provider: {provider}")


class CodeEmbedder:
    """Handles embedding generation for code chunks using Ollama."""

    def __init__(
        self,
        model: str = DEFAULT_MODEL,
        base_url: str = DEFAULT_OLLAMA_URL,
    ):
        """Initialize the embedder with Ollama configuration.

        Args:
            model: The Ollama model to use for embeddings
            base_url: The base URL for the Ollama API
        """
        self.model = model
        self.base_url = base_url
        self.embeddings = OllamaEmbeddings(
            model=model,
            base_url=base_url,
        )
        logger.debug(
            f"Initialized CodeEmbedder with model={model}, base_url={base_url}"
        )

    def check_health(self) -> bool:
        """Check if Ollama is reachable and the model is available.

        Returns:
            True if Ollama is reachable and model is available, False otherwise
        """
        try:
            response = requests.get(f"{self.base_url}/api/tags", timeout=5)
            response.raise_for_status()

            data = response.json()
            models = [m.get("name", "") for m in data.get("models", [])]

            if self.model in models:
                logger.debug(f"Health check passed: model {self.model} is available")
                return True
            else:
                model_base = self.model.split(":")[0]
                available_models = [m for m in models if model_base in m]
                if available_models:
                    logger.debug(
                        f"Health check passed: found model variants {available_models}"
                    )
                    return True
                logger.error(
                    f"Model {self.model} not found in available models: {models}"
                )
                return False

        except requests.exceptions.ConnectionError:
            logger.error(f"Cannot connect to Ollama at {self.base_url}")
            return False
        except requests.exceptions.Timeout:
            logger.error(f"Timeout connecting to Ollama at {self.base_url}")
            return False
        except requests.exceptions.RequestException as e:
            logger.error(f"Health check failed: {e}")
            return False

    def embed_chunks(self, chunks: list[dict], batch_size: int = 64) -> list[dict]:
        """Embed a list of code chunks with search_document prefix.

        Args:
            chunks: List of chunk dictionaries with 'text' field
            batch_size: Number of chunks to embed per batch

        Returns:
            List of chunks with 'embedding' field added (768-dim vector)
        """
        if not chunks:
            return []

        total_batches = (len(chunks) + batch_size - 1) // batch_size
        result_chunks = []

        for batch_idx in range(total_batches):
            start_idx = batch_idx * batch_size
            end_idx = min(start_idx + batch_size, len(chunks))
            batch = chunks[start_idx:end_idx]

            logger.info(f"Embedding batch {batch_idx + 1}/{total_batches}...")

            texts = [f"{EMBEDDING_PREFIX}{chunk['text']}" for chunk in batch]
            embeddings = self.embeddings.embed_documents(texts)

            for chunk, embedding in zip(batch, embeddings):
                chunk_with_embedding = chunk.copy()
                chunk_with_embedding["embedding"] = embedding
                result_chunks.append(chunk_with_embedding)

            logger.debug(f"Embedded batch {batch_idx + 1}: {len(batch)} chunks")

        logger.info(f"Successfully embedded {len(result_chunks)} chunks")
        return result_chunks

    def embed_query(self, query: str) -> list[float]:
        """Embed a single query string with search_query prefix.

        Args:
            query: The query string to embed

        Returns:
            768-dimensional embedding vector
        """
        prefixed_query = f"search_query: {query}"
        embedding = self.embeddings.embed_query(prefixed_query)
        logger.debug(f"Embedded query: '{query[:50]}...' (truncated)")
        return embedding
