#!/usr/bin/env python3
"""Standalone script to test the Jina embedding model locally."""

import logging
import sys
import time

import torch
from transformers import AutoModel, AutoTokenizer

# Configure logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

MODEL_NAME = "jinaai/jina-code-embeddings-1.5b"
MAX_LENGTH = 512

# Task-specific prefixes used in the actual pipeline
PREFIXES = {
    "query": "Find the most relevant code snippet given the following query:\n",
    "passage": "Candidate code snippet:\n",
}


def test_model():
    logger.info(f"Loading model: {MODEL_NAME}")
    try:
        # local_files_only=False to ensure it can download if missing,
        # remove if you strictly want to test cached files
        tokenizer = AutoTokenizer.from_pretrained(MODEL_NAME, trust_remote_code=True)
        model = AutoModel.from_pretrained(
            MODEL_NAME, trust_remote_code=True, torch_dtype=torch.bfloat16
        )
    except Exception as e:
        logger.error(f"Failed to load model: {e}")
        sys.exit(1)

    # Device setup
    if torch.backends.mps.is_available():
        device = "mps"
    elif torch.cuda.is_available():
        device = "cuda"
    else:
        device = "cpu"

    logger.info(f"Moving model to device: {device}")
    model.to(device)
    model.eval()

    # Test cases mimicking the pipeline
    test_cases = [
        {
            "type": "Passage (Short Code)",
            "text": PREFIXES["passage"] + "function add(a, b) { return a + b; }",
        },
        {
            "type": "Query (Natural Language)",
            "text": PREFIXES["query"]
            + "How to implement a binary search tree in TypeScript?",
        },
        {
            "type": "Long Code Snippet (Boundary Test)",
            "text": PREFIXES["passage"]
            + "class ComplexClass {\n"
            + "    constructor() { this.data = []; }\n" * 60
            + "}",
        },
    ]

    for case in test_cases:
        logger.info(f"--- Testing: {case['type']} ---")
        text = case["text"]
        logger.info(f"Input text length: {len(text)} chars")

        # Tokenize
        logger.info("Tokenizing...")
        inputs = tokenizer(
            text,
            padding=True,
            truncation=True,
            max_length=MAX_LENGTH,
            return_tensors="pt",
        )
        inputs = {k: v.to(device) for k, v in inputs.items()}

        # Embed
        logger.info("Generating embedding...")
        start_time = time.time()
        with torch.no_grad():
            outputs = model(**inputs, return_dict=True)

            # Pooling logic matching src/embedder.py
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

        elapsed = time.time() - start_time
        vec = embeddings.cpu().squeeze(0).tolist()

        # Verification
        norm = sum(x**2 for x in vec) ** 0.5
        logger.info(f"✅ Success!")
        logger.info(f"⏱️ Time taken: {elapsed:.4f} seconds")
        logger.info(f"📏 Embedding dimension: {len(vec)}")
        logger.info(f"📐 Vector norm (should be ~1.0): {norm:.6f}")
        logger.info(f"🔍 First 5 values: {vec[:5]}")

        # Memory cleanup
        del outputs, last_hidden, embeddings, inputs
        if device == "mps":
            torch.mps.empty_cache()

    logger.info("All tests completed successfully.")


if __name__ == "__main__":
    test_model()
