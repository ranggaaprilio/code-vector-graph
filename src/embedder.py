"""Embedder module for generating embeddings using HuggingFace."""

import logging
import sys
from abc import ABC, abstractmethod
from typing import List

import torch
from transformers import AutoModel, AutoTokenizer

from .config import MODEL_CONFIGS, DEFAULT_MODEL_ID

logger = logging.getLogger(__name__)

JINA_TASK_PREFIXES = {
    "code2code": {
        "query": "Find an equivalent code snippet given the following code snippet:\n",
        "passage": "Candidate code snippet:\n",
    },
    "nl2code": {
        "query": "Find the most relevant code snippet given the following query:\n",
        "passage": "Candidate code snippet:\n",
    },
}


class Embedder(ABC):
    """Abstract base class for embedding providers."""

    @abstractmethod
    def embed_chunks(self, chunks: list[dict], batch_size: int = 64) -> list[dict]:
        pass

    @abstractmethod
    def embed_query(self, query: str) -> list[float]:
        pass

    @abstractmethod
    def check_health(self) -> bool:
        pass

    @abstractmethod
    def get_dimensions(self) -> int:
        pass


class HuggingFaceEmbedder(Embedder):
    """HuggingFace embedding implementation using transformers AutoModel/AutoTokenizer."""

    def __init__(
        self,
        model: str | None = None,
        model_id: str | None = None,
        device: str | None = None,
        dtype: str | None = None,
    ):
        self.model_id = model_id or DEFAULT_MODEL_ID
        self.model_config = MODEL_CONFIGS[self.model_id]
        self.model_name = model or self.model_config["model_name"]
        self.prefixes = self.model_config["prefixes"]
        self.dimensions = self.model_config["dimensions"]

        if device and device != "auto":
            self.device = device
        elif torch.backends.mps.is_available():
            self.device = "mps"
        elif torch.cuda.is_available():
            self.device = "cuda"
        else:
            self.device = "cpu"

        logger.info(f"Loading HuggingFace model {self.model_name}...")

        is_rocm = (
            torch.cuda.is_available()
            and hasattr(torch.version, "hip")
            and torch.version.hip is not None
        )

        dtype = self._resolve_dtype(dtype, is_rocm)
        logger.info(f"Using dtype={dtype} for device={self.device}")

        try:
            self.tokenizer = AutoTokenizer.from_pretrained(
                self.model_name, trust_remote_code=True, local_files_only=True
            )
            self.model = AutoModel.from_pretrained(
                self.model_name,
                trust_remote_code=True,
                local_files_only=True,
                torch_dtype=dtype,
            )
        except (OSError, RuntimeError, ValueError) as e:
            logger.error(f"Failed to load HuggingFace model '{self.model_name}': {e}")
            print(
                f"\nERROR: Failed to load model '{self.model_name}'.",
                file=sys.stderr,
            )
            print(f"Details: {e}", file=sys.stderr)
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
            raise
        self.model.eval()
        try:
            self.model.to(self.device)
        except (RuntimeError, ValueError, OSError) as e:
            logger.warning(
                f"Failed to move model to {self.device}: {e}. Falling back to CPU."
            )
            self.device = "cpu"
            self.model.to(self.device)

        logger.info(
            f"Initialized HuggingFaceEmbedder with model={self.model_name}, device={self.device}"
        )

    _VALID_DTYPES = ("float16", "bfloat16", "float32")

    def _resolve_dtype(self, dtype: str | None, is_rocm: bool) -> "torch.dtype":
        """Resolve the torch dtype to load the model in.

        An explicit dtype (``float16``/``bfloat16``/``float32``) always wins.
        Otherwise ("auto"/None) we pick a device-appropriate default:

        - MPS (Apple Silicon): ``bfloat16`` — half the memory and roughly 2x the
          throughput of float32, while keeping float32's exponent range so
          inference stays numerically safe (no overflow/NaN risk like float16).
        - ROCm (AMD): ``float32`` — the half-precision path is historically
          unstable there.
        - CUDA: the model's configured dtype (float16 for nomic, bfloat16 for jina).
        - CPU: ``float32`` — half precision on CPU is slow and poorly supported.
        """
        if dtype and dtype != "auto":
            if dtype not in self._VALID_DTYPES:
                raise ValueError(
                    f"Unsupported dtype '{dtype}'. Choose one of: "
                    f"{', '.join(('auto', *self._VALID_DTYPES))}"
                )
            return getattr(torch, dtype)

        if is_rocm:
            logger.info(
                "ROCm (AMD GPU) detected - using float32 instead of %s",
                self.model_config["dtype"],
            )
            return torch.float32
        if self.device == "mps":
            return torch.bfloat16
        if self.device == "cuda":
            return getattr(torch, self.model_config["dtype"])
        return torch.float32

    def _prepend_passage_prefix(self, texts: List[str]) -> List[str]:
        """Prepend task-specific passage prefix if configured for the model."""
        if self.prefixes is not None:
            prefix = self.prefixes["code2code"]["passage"]
            texts = [prefix + t for t in texts]
        return texts

    def _prepend_query_prefix(self, query: str) -> str:
        """Prepend task-specific query prefix if configured for the model."""
        if self.prefixes is not None:
            prefix = self.prefixes["nl2code"]["query"]
            return prefix + query
        return query

    def _clear_device_cache(self) -> None:
        if self.device == "mps":
            torch.mps.empty_cache()
        elif self.device == "cuda":
            torch.cuda.empty_cache()

    def _is_mps_out_of_memory(self, error: RuntimeError) -> bool:
        return self.device == "mps" and "MPS backend out of memory" in str(error)

    def _embed_text_batch(self, batch_texts: List[str]) -> list[list[float]]:
        inputs = self.tokenizer(
            batch_texts,
            padding=True,
            truncation=True,
            max_length=512,
            return_tensors="pt",
        )

        try:
            for k, v in inputs.items():
                if isinstance(v, torch.Tensor):
                    logger.debug(f"Moving {k} to device")
                    inputs[k] = v.to(self.device)

            outputs = self.model(**inputs, return_dict=True)
            last_hidden = outputs.last_hidden_state
            attention_mask = inputs.get("attention_mask")
            if attention_mask is not None:
                sequence_lengths = (attention_mask.sum(dim=1) - 1).to(
                    last_hidden.device
                )
                embeddings = last_hidden[
                    torch.arange(last_hidden.size(0), device=last_hidden.device),
                    sequence_lengths,
                ]
            else:
                embeddings = last_hidden[:, -1, :]
            embeddings = torch.nn.functional.normalize(embeddings, p=2, dim=-1)
            embeddings_list = embeddings.cpu().tolist()

            del outputs, last_hidden, embeddings
            return embeddings_list
        finally:
            for v in inputs.values():
                if isinstance(v, torch.Tensor):
                    del v
            del inputs
            # NOTE: we deliberately do NOT call empty_cache() here. Clearing the
            # MPS/CUDA cache every batch forces a device sync that stalls the
            # pipeline; the allocator reuses cached blocks between batches so
            # peak memory stays bounded. The cache is cleared on the OOM-retry
            # path (see embed_chunks) and once per file-batch (see main.py).

    def embed_chunks(self, chunks: list[dict], batch_size: int = 64) -> list[dict]:
        if not chunks:
            return []

        texts = []
        for ch in chunks:
            if isinstance(ch, dict) and "text" in ch:
                texts.append(ch["text"])
            else:
                texts.append(str(ch))

        texts = self._prepend_passage_prefix(texts)

        total = len(texts)
        # Order by length so each batch holds similar-length texts. The tokenizer
        # pads every batch to its longest sequence, so length-bucketing minimizes
        # wasted compute on padding. sorted() is stable, so equal-length texts keep
        # their original relative order. We write results back by original index,
        # so the returned list matches the input order regardless of processing order.
        order = sorted(range(total), key=lambda i: len(texts[i]))

        result_chunks: List[dict | None] = [None] * total
        total_batches = (total + batch_size - 1) // batch_size
        logger.info(
            f"Starting embedding of {total} chunks in ~{total_batches} batches (batch_size={batch_size})..."
        )

        with torch.no_grad():
            pos = 0
            batch_idx = 0
            current_batch_size = batch_size
            while pos < total:
                end = min(pos + current_batch_size, total)
                batch_indices = order[pos:end]
                batch_texts = [texts[i] for i in batch_indices]
                logger.info(
                    "Embedding batch %s (%s/%s chunks done, %s in batch)...",
                    batch_idx + 1,
                    pos,
                    total,
                    len(batch_texts),
                )

                try:
                    embeddings_list = self._embed_text_batch(batch_texts)
                except RuntimeError as e:
                    if self._is_mps_out_of_memory(e) and current_batch_size > 1:
                        next_batch_size = max(1, current_batch_size // 2)
                        logger.warning(
                            "MPS out of memory while embedding %s chunks. "
                            "Retrying with batch_size=%s.",
                            len(batch_texts),
                            next_batch_size,
                        )
                        current_batch_size = next_batch_size
                        self._clear_device_cache()
                        continue
                    if self._is_mps_out_of_memory(e):
                        logger.error(
                            "MPS out of memory while embedding a single chunk. "
                            "Try reducing --chunk-size or run with CPU."
                        )
                    raise

                logger.info(
                    f"Batch {batch_idx + 1}/~{total_batches} embedded successfully"
                )

                for emb, idx in zip(embeddings_list, batch_indices):
                    orig = chunks[idx]
                    chunk = (
                        orig.copy()
                        if isinstance(orig, dict)
                        else {"text": texts[idx]}
                    )
                    chunk["embedding"] = emb
                    result_chunks[idx] = chunk
                pos = end
                batch_idx += 1

        logger.info(f"Embedding complete: {total} chunks processed")
        return result_chunks

    def embed_query(self, query: str) -> list[float]:
        query = self._prepend_query_prefix(query)
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
            outputs = self.model(**inputs, return_dict=True)
            last_hidden = outputs.last_hidden_state
            attention_mask = inputs.get("attention_mask")
            if attention_mask is not None:
                sequence_length = (attention_mask.sum(dim=1) - 1).to(
                    last_hidden.device
                )
                embedding = last_hidden[
                    torch.arange(last_hidden.size(0), device=last_hidden.device),
                    sequence_length,
                ]
            else:
                embedding = last_hidden[:, -1, :]
            embedding = torch.nn.functional.normalize(embedding, p=2, dim=-1)
            vec = embedding.cpu().squeeze(0).tolist()
        return vec

    def check_health(self) -> bool:
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
        return self.dimensions


def create_embedder(model_id: str | None = None, **kwargs) -> HuggingFaceEmbedder:
    config = MODEL_CONFIGS[model_id or DEFAULT_MODEL_ID]
    return HuggingFaceEmbedder(
        model=kwargs.pop("model", config["model_name"]),
        model_id=model_id or DEFAULT_MODEL_ID,
        **kwargs,
    )


__all__ = ["Embedder", "HuggingFaceEmbedder", "create_embedder", "JINA_TASK_PREFIXES"]
