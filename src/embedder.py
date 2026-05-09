"""Embedder module for generating embeddings using HuggingFace."""

import logging
import sys
from abc import ABC, abstractmethod
from typing import List

import torch
from transformers import AutoModel, AutoTokenizer

from .config import (
    EMBEDDING_DIMENSIONS,
    EMBEDDING_PROVIDERS,
)

logger = logging.getLogger(__name__)


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

    def __init__(self, model: str | None = None, device: str | None = None):
        self.model_name = model or EMBEDDING_PROVIDERS["huggingface"]["model"]
        if device:
            self.device = device
        elif torch.backends.mps.is_available():
            self.device = "mps"
        elif torch.cuda.is_available():
            self.device = "cuda"
        else:
            self.device = "cpu"

        logger.info(f"Loading HuggingFace model {self.model_name}...")
        try:
            self.tokenizer = AutoTokenizer.from_pretrained(
                self.model_name, trust_remote_code=True, local_files_only=True
            )
            self.model = AutoModel.from_pretrained(
                self.model_name, trust_remote_code=True, local_files_only=True,
                torch_dtype=torch.float16,
            )
        except Exception as e:
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
        except Exception as e:
            logger.warning(f"Failed to move model to {self.device}: {e}. Falling back to CPU.")
            self.device = "cpu"
            self.model.to(self.device)

        logger.info(f"Initialized HuggingFaceEmbedder with model={self.model_name}, device={self.device}")

    def _token_truncation_warnings(self, texts: List[str]) -> int:
        count = 0
        for t in texts:
            try:
                tokens = self.tokenizer.encode(t, max_length=512, truncation=False)
                if len(tokens) > 512:
                    count += 1
            except Exception:
                continue
        return count

    def embed_chunks(self, chunks: list[dict], batch_size: int = 64) -> list[dict]:
        if not chunks:
            return []

        texts = []
        for ch in chunks:
            if isinstance(ch, dict) and "text" in ch:
                texts.append(ch["text"])
            else:
                texts.append(str(ch))

        logger.info(f"Checking {len(texts)} chunks for token truncation...")
        truncated_count = self._token_truncation_warnings(texts)
        if truncated_count:
            logger.warning(
                f"Warning: {truncated_count} chunks exceeded 512 tokens and will be truncated"
            )

        total = len(texts)
        result_chunks: List[dict] = []
        total_batches = (total + batch_size - 1) // batch_size
        logger.info(f"Starting embedding of {total} chunks in {total_batches} batches (batch_size={batch_size})...")

        with torch.no_grad():
            for batch_idx in range(total_batches):
                start = batch_idx * batch_size
                end = min(start + batch_size, total)
                batch_texts = texts[start:end]
                logger.info(f"Embedding batch {batch_idx + 1}/{total_batches} ({len(batch_texts)} chunks)...")

                inputs = self.tokenizer(
                    batch_texts,
                    padding=True,
                    truncation=True,
                    max_length=512,
                    return_tensors="pt",
                )
                for k, v in inputs.items():
                    if isinstance(v, torch.Tensor):
                        inputs[k] = v.to(self.device)

                logger.debug(f"Running model forward for batch {batch_idx + 1}...")
                outputs = self.model(**inputs, return_dict=True)
                logger.debug(f"Model forward complete for batch {batch_idx + 1}")

                last_hidden = outputs.last_hidden_state
                attention_mask = inputs.get("attention_mask")
                if attention_mask is not None:
                    sequence_lengths = attention_mask.sum(dim=1) - 1
                    embeddings = last_hidden[
                        torch.arange(last_hidden.size(0)), sequence_lengths
                    ]
                else:
                    embeddings = last_hidden[:, -1, :]
                embeddings = torch.nn.functional.normalize(embeddings, p=2, dim=-1)

                embeddings_list = embeddings.cpu().tolist()
                logger.info(f"Batch {batch_idx + 1}/{total_batches} embedded successfully")

                del outputs, last_hidden, embeddings
                for v in inputs.values():
                    if isinstance(v, torch.Tensor):
                        del v
                del inputs
                if self.device == "mps":
                    torch.mps.empty_cache()

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

        logger.info(f"Embedding complete: {len(result_chunks)} chunks processed")
        return result_chunks

    def embed_query(self, query: str) -> list[float]:
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
                sequence_length = attention_mask.sum(dim=1) - 1
                embedding = last_hidden[
                    torch.arange(last_hidden.size(0)), sequence_length
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
        return EMBEDDING_PROVIDERS["huggingface"]["dimensions"]


def create_embedder(**kwargs) -> HuggingFaceEmbedder:
    return HuggingFaceEmbedder(**kwargs)
