#!/usr/bin/env python3
"""Batch-mode test script that replicates src/embedder.py exactly to isolate the hang."""

import logging
import sys
import time

import torch
from transformers import AutoModel, AutoTokenizer

# ---------------------------------------------------------------------------
# Logging: use DEBUG so we see every micro-step; force flush after every line
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    stream=sys.stdout,
)
logger = logging.getLogger("test_jina_batch")
for handler in logging.root.handlers:
    handler.flush = sys.stdout.flush


# ---------------------------------------------------------------------------
# Replicate constants / prefixes from src/embedder.py
# ---------------------------------------------------------------------------
MODEL_NAME = "jinaai/jina-code-embeddings-1.5b"

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


def _get_device():
    """Mirror HuggingFaceEmbedder.__init__ device selection."""
    if torch.backends.mps.is_available():
        return "mps"
    if torch.cuda.is_available():
        return "cuda"
    return "cpu"


def _load():
    """Mirror HuggingFaceEmbedder.__init__ loading logic exactly."""
    device = _get_device()
    logger.info(f"[LOAD] Selected device: {device}")

    logger.info(
        f"[LOAD] AutoTokenizer.from_pretrained({MODEL_NAME}, trust_remote_code=True, local_files_only=True)"
    )
    tokenizer = AutoTokenizer.from_pretrained(
        MODEL_NAME, trust_remote_code=True, local_files_only=True
    )
    logger.info("[LOAD] Tokenizer loaded.")

    logger.info(
        f"[LOAD] AutoModel.from_pretrained({MODEL_NAME}, trust_remote_code=True, "
        f"local_files_only=True, torch_dtype=torch.bfloat16)"
    )
    model = AutoModel.from_pretrained(
        MODEL_NAME,
        trust_remote_code=True,
        local_files_only=True,
        torch_dtype=torch.bfloat16,
    )
    logger.info("[LOAD] Model loaded.")

    model.eval()
    logger.info(f"[LOAD] Calling model.to({device})...")
    model.to(device)
    logger.info(f"[LOAD] Model on {device}.")
    return tokenizer, model, device


def _embed_chunks(tokenizer, model, device, chunks, batch_size=64):
    """Mirror HuggingFaceEmbedder.embed_chunks exactly, with extra trace logs."""
    if not chunks:
        return []

    # 1) Extract texts
    texts = []
    for ch in chunks:
        if isinstance(ch, dict) and "text" in ch:
            texts.append(ch["text"])
        else:
            texts.append(str(ch))

    # 2) Prepend Jina passage prefix
    texts = [JINA_TASK_PREFIXES["code2code"]["passage"] + t for t in texts]

    total = len(texts)
    result_chunks = []
    total_batches = (total + batch_size - 1) // batch_size
    logger.info(
        f"[EMBED] total_chunks={total}, batch_size={batch_size}, total_batches={total_batches}"
    )

    with torch.no_grad():
        for batch_idx in range(total_batches):
            start = batch_idx * batch_size
            end = min(start + batch_size, total)
            batch_texts = texts[start:end]

            logger.info(
                f"[EMBED] --- Batch {batch_idx + 1}/{total_batches} "
                f"({len(batch_texts)} texts) ---"
            )

            # 3) Tokenize (padding=True is the critical difference from the single-text test)
            logger.info(
                "[EMBED] Calling tokenizer(padding=True, truncation=True, max_length=512, return_tensors='pt')..."
            )
            t0 = time.time()
            inputs = tokenizer(
                batch_texts,
                padding=True,
                truncation=True,
                max_length=512,
                return_tensors="pt",
            )
            t1 = time.time()
            logger.info(
                f"[EMBED] Tokenizer returned in {t1 - t0:.3f}s. Keys: {list(inputs.keys())}"
            )

            # 4) Move tensors to device (exact loop from embedder.py)
            for k, v in inputs.items():
                logger.info(
                    f"[EMBED] Input tensor '{k}': shape={v.shape}, dtype={v.dtype}"
                )
                if isinstance(v, torch.Tensor):
                    logger.info(f"[EMBED] Moving '{k}' to {device}...")
                    inputs[k] = v.to(device)
                    logger.info(f"[EMBED] Moved '{k}'.")

            # 5) Model forward — this is line ~165 in embedder.py where the hang occurs
            logger.info("[EMBED] >>> Entering model forward pass...")
            t2 = time.time()
            try:
                outputs = model(**inputs, return_dict=True)
            except Exception as exc:
                logger.exception("[EMBED] Model forward FAILED with exception")
                raise
            t3 = time.time()
            logger.info(f"[EMBED] <<< Model forward completed in {t3 - t2:.3f}s.")

            # 6) Pooling logic (exact replica)
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
            logger.info(
                f"[EMBED] Batch {batch_idx + 1}/{total_batches} done. "
                f"Produced {len(embeddings_list)} embeddings."
            )

            # 7) Cleanup (exact replica)
            del outputs, last_hidden, embeddings
            for v in inputs.values():
                if isinstance(v, torch.Tensor):
                    del v
            del inputs
            if device == "mps":
                torch.mps.empty_cache()

            for i, emb in enumerate(embeddings_list):
                idx = start + i
                orig = chunks[idx]
                chunk = (
                    orig.copy() if isinstance(orig, dict) else {"text": batch_texts[i]}
                )
                chunk["embedding"] = emb
                result_chunks.append(chunk)

    logger.info(f"[EMBED] All batches finished. result_chunks={len(result_chunks)}")
    return result_chunks


def _make_chunks(count, min_len=50, max_len=3000):
    """
    Generate synthetic chunks that look like real pipeline output.
    We vary lengths so that padding=True has to pad to the longest
    sequence in each batch — this is the most likely trigger for the hang.
    """
    chunks = []
    for i in range(count):
        length = min_len + (i * 7919) % (max_len - min_len)  # pseudo-random spread
        body = "  const x = " + str(i) + ";\n" * (length // 20)
        code = f"function synthetic_{i}() {{\n{body}}}\n"
        chunks.append({"text": code, "id": f"chunk_{i}"})
    return chunks


def _run_test(name, tokenizer, model, device, chunk_count, batch_size):
    logger.info("\n" + "=" * 60)
    logger.info(f"[{name}] chunk_count={chunk_count}, batch_size={batch_size}")
    logger.info("=" * 60)
    chunks = _make_chunks(chunk_count)
    res = _embed_chunks(tokenizer, model, device, chunks, batch_size=batch_size)
    logger.info(f"[{name}] SUCCESS — produced {len(res)} embeddings")
    if res:
        logger.info(f"[{name}] First embedding dimension: {len(res[0]['embedding'])}")


def main():
    logger.info("Starting batch-mode replication test for src/embedder.py")

    tokenizer, model, device = _load()

    # Progressive tests: single → small batch → medium batch → large batch
    _run_test("TEST_1_SINGLE", tokenizer, model, device, chunk_count=1, batch_size=1)
    _run_test("TEST_2_BATCH_2", tokenizer, model, device, chunk_count=2, batch_size=2)
    _run_test("TEST_3_BATCH_8", tokenizer, model, device, chunk_count=8, batch_size=8)
    _run_test(
        "TEST_4_BATCH_64", tokenizer, model, device, chunk_count=64, batch_size=64
    )

    logger.info("\n" + "=" * 60)
    logger.info("ALL TESTS PASSED")
    logger.info("=" * 60)


if __name__ == "__main__":
    main()
