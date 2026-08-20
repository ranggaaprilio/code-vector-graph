#!/usr/bin/env python3
"""Pre-download an embedding model + tokenizer from HuggingFace into the local cache.

Downloading ahead of time keeps the first `cvg-ingest` run from stalling on a
multi-GB fetch, and surfaces auth problems (a missing or unscoped HF_TOKEN)
before a long indexing job starts.
"""

import argparse
import logging
import os
import sys

from dotenv import load_dotenv

load_dotenv()

from code_vector_graph.config import (  # noqa: E402
    DEFAULT_MODEL_ID,
    MODEL_CONFIGS,
    get_model_config,
)

logger = logging.getLogger(__name__)


def _resolve_token() -> str:
    """Read HF_TOKEN from the environment, failing with an actionable message."""
    token = os.getenv("HF_TOKEN")
    if not token:
        raise ValueError(
            "HF_TOKEN not found. Please set it in your .env file. "
            "Copy .env.example to .env and add your HuggingFace token."
        )
    return token


def download_model(model_id: str = DEFAULT_MODEL_ID, *, smoke_test: bool = True) -> str:
    """Download the tokenizer + weights for `model_id` and optionally smoke-test them.

    Args:
        model_id: Key into MODEL_CONFIGS — "nomic" or "jina".
        smoke_test: Run one forward pass to prove the weights actually load.

    Returns:
        The resolved HuggingFace model name that was downloaded.
    """
    os.environ["HF_HOME"] = os.environ.get(
        "HF_HOME", os.path.expanduser("~/.cache/huggingface")
    )
    token = _resolve_token()
    os.environ["HF_TOKEN"] = token

    # Imported lazily so `--help` doesn't pay for loading torch/transformers.
    import torch
    from transformers import AutoModel, AutoTokenizer

    model_name = get_model_config(model_id)["model_name"]
    print(f"Downloading {model_name}...")

    print("Downloading tokenizer...")
    tokenizer = AutoTokenizer.from_pretrained(
        model_name, trust_remote_code=True, token=token
    )
    print("✓ Tokenizer downloaded")

    print("Downloading model (this may take a few minutes)...")
    model = AutoModel.from_pretrained(model_name, trust_remote_code=True, token=token)
    print("✓ Model downloaded successfully")

    if smoke_test:
        print("\nTesting model...")
        test_input = tokenizer("def hello(): pass", return_tensors="pt")
        with torch.no_grad():
            output = model(**test_input)
        # Output shape lives under a different attribute per architecture.
        if hasattr(output, "last_hidden_state"):
            print(f"✓ Model works! Output shape: {output.last_hidden_state.shape}")
        elif hasattr(output, "pooler_output"):
            print(f"✓ Model works! Output shape: {output.pooler_output.shape}")
        elif isinstance(output, torch.Tensor):
            print(f"✓ Model works! Output shape: {output.shape}")
        else:
            print(f"✓ Model works! Output type: {type(output)}")

    return model_name


def create_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="cvg-download-model",
        description="Pre-download an embedding model from HuggingFace.",
    )
    p.add_argument(
        "--model",
        default=DEFAULT_MODEL_ID,
        choices=list(MODEL_CONFIGS.keys()),
        help=f"Model to download (default: {DEFAULT_MODEL_ID})",
    )
    p.add_argument(
        "--no-smoke-test",
        action="store_true",
        help="Skip the post-download forward pass",
    )
    return p


def main() -> int:
    args = create_parser().parse_args()
    try:
        model_name = download_model(args.model, smoke_test=not args.no_smoke_test)
    except Exception as e:
        print(f"✗ Error: {e}", file=sys.stderr)
        return 1

    print("\n" + "=" * 60)
    print("SUCCESS! Model is ready to use.")
    print("=" * 60)
    print(f"\nIndex a repository with it:\n  cvg-ingest --repo-path /path/to/repo --model {args.model}")
    print(f"  (resolved model: {model_name})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
