"""CLI argument parsing for Code Vector Graph."""

import argparse
import logging
import sys
from pathlib import Path

from src.config import (
    DEFAULT_CHUNK_OVERLAP,
    DEFAULT_CHUNK_SIZE,
    DEFAULT_COLLECTION_NAME,
    DEFAULT_MODEL_ID,
    DEFAULT_QDRANT_URL,
    MODEL_CONFIGS,
    NEO4J_URI,
    NEO4J_USER,
    NEO4J_PASSWORD,
)

logger = logging.getLogger(__name__)


def create_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="code-vector-graph",
        description="Embed JS/TS code into Qdrant using Tree-sitter and HuggingFace transformers.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s --repo-path ./my-project
  %(prog)s --repo-path ./my-project --dry-run --verbose
  %(prog)s --repo-path ./my-project --qdrant-url http://localhost:6333
        """.strip(),
    )

    parser.add_argument(
        "--repo-path",
        type=str,
        required=True,
        help="Path to repository to process (required)",
    )

    parser.add_argument(
        "--qdrant-url",
        type=str,
        default=DEFAULT_QDRANT_URL,
        help=f"Qdrant server URL (default: {DEFAULT_QDRANT_URL})",
    )

    parser.add_argument(
        "--collection-name",
        type=str,
        default=DEFAULT_COLLECTION_NAME,
        help=f"Qdrant collection name (default: {DEFAULT_COLLECTION_NAME})",
    )

    parser.add_argument(
        "--chunk-size",
        type=int,
        default=DEFAULT_CHUNK_SIZE,
        help=f"Token chunk size (default: {DEFAULT_CHUNK_SIZE})",
    )

    parser.add_argument(
        "--chunk-overlap",
        type=int,
        default=DEFAULT_CHUNK_OVERLAP,
        help=f"Token overlap size (default: {DEFAULT_CHUNK_OVERLAP})",
    )

    parser.add_argument(
        "--batch-size",
        type=int,
        default=64,
        help="Embedding batch size (default: 64)",
    )

    parser.add_argument(
        "--glossary-file",
        type=str,
        default="glossary.yml",
        help="Manual glossary YAML file path (default: glossary.yml)",
    )

    parser.add_argument(
        "--no-graph",
        action="store_true",
        help="Skip Neo4j graph ingestion",
    )

    parser.add_argument(
        "--neo4j-uri",
        type=str,
        default=NEO4J_URI,
        help=f"Neo4j bolt URI (default: {NEO4J_URI})",
    )

    parser.add_argument(
        "--neo4j-user",
        type=str,
        default=NEO4J_USER,
        help=f"Neo4j username (default: {NEO4J_USER})",
    )

    parser.add_argument(
        "--neo4j-password",
        type=str,
        default=NEO4J_PASSWORD,
        help=f"Neo4j password (default: {NEO4J_PASSWORD})",
    )

    parser.add_argument(
        "--model",
        type=str,
        default=DEFAULT_MODEL_ID,
        choices=list(MODEL_CONFIGS.keys()),
        help=f"Embedding model to use (default: {DEFAULT_MODEL_ID}). Options: {', '.join(MODEL_CONFIGS.keys())}",
    )

    parser.add_argument(
        "--device",
        type=str,
        default="auto",
        choices=["auto", "mps", "cuda", "cpu"],
        help="Compute device for embeddings (default: auto-detect)",
    )

    parser.add_argument(
        "--dtype",
        type=str,
        default="auto",
        choices=["auto", "float16", "bfloat16", "float32"],
        help=(
            "Model precision (default: auto). 'auto' uses bfloat16 on Apple "
            "Silicon/MPS for ~2x throughput and half the memory vs float32."
        ),
    )

    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Run discovery, parsing, chunking without embedding/storing",
    )

    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Print progress info",
    )

    return parser


def parse_args(args: list[str] | None = None) -> argparse.Namespace:
    parser = create_parser()
    parsed = parser.parse_args(args)

    repo_path = Path(parsed.repo_path)
    if not repo_path.exists():
        parser.error(f"Repository path does not exist: {parsed.repo_path}")
    if not repo_path.is_dir():
        parser.error(f"Repository path is not a directory: {parsed.repo_path}")

    if parsed.chunk_size <= 0:
        parser.error(f"Chunk size must be positive, got: {parsed.chunk_size}")
    if parsed.chunk_overlap < 0:
        parser.error(f"Chunk overlap must be non-negative, got: {parsed.chunk_overlap}")
    if parsed.chunk_overlap >= parsed.chunk_size:
        parser.error(
            f"Chunk overlap ({parsed.chunk_overlap}) must be less than chunk size ({parsed.chunk_size})"
        )

    if parsed.batch_size <= 0:
        parser.error(f"Batch size must be positive, got: {parsed.batch_size}")

    return parsed


def setup_logging(verbose: bool) -> None:
    level = logging.INFO if verbose else logging.WARNING
    logging.basicConfig(
        level=level,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    if not verbose:
        logging.getLogger("urllib3").setLevel(logging.WARNING)
        logging.getLogger("requests").setLevel(logging.WARNING)
        logging.getLogger("httpx").setLevel(logging.WARNING)


__all__ = ["create_parser", "parse_args", "setup_logging"]
