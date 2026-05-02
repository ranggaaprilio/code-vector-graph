"""CLI argument parsing for Code Vector Graph."""

import argparse
import logging
import sys
from pathlib import Path

from src.config import (
    DEFAULT_CHUNK_OVERLAP,
    DEFAULT_CHUNK_SIZE,
    DEFAULT_COLLECTION_NAME,
    DEFAULT_PROVIDER,
    DEFAULT_MODEL,
    DEFAULT_OLLAMA_URL,
    DEFAULT_QDRANT_URL,
    EMBEDDING_PROVIDERS,
)

logger = logging.getLogger(__name__)


def create_parser() -> argparse.ArgumentParser:
    """Create and configure the argument parser."""
    parser = argparse.ArgumentParser(
        prog="code-vector-graph",
        description="Embed JS/TS code into Qdrant using Tree-sitter, Ollama, and tokenizers.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s --repo-path ./my-project
  %(prog)s --repo-path ./my-project --embedding-provider huggingface
  %(prog)s --repo-path ./my-project --dry-run --verbose
  %(prog)s --repo-path ./my-project --qdrant-url http://localhost:6333 --model nomic-embed-text:latest
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
        "--ollama-url",
        type=str,
        default=DEFAULT_OLLAMA_URL,
        help=f"Ollama server URL (default: {DEFAULT_OLLAMA_URL})",
    )

    parser.add_argument(
        "--model",
        type=str,
        default=DEFAULT_MODEL,
        help=f"Ollama embedding model (default: {DEFAULT_MODEL})",
    )

    parser.add_argument(
        "--embedding-provider",
        type=str,
        default=DEFAULT_PROVIDER,
        choices=list(EMBEDDING_PROVIDERS.keys()),
        help=f"Embedding provider to use (default: {DEFAULT_PROVIDER})",
    )

    parser.add_argument(
        "--batch-size",
        type=int,
        default=64,
        help="Embedding batch size (default: 64)",
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
    """
    Parse command line arguments.

    Args:
        args: Command line arguments (defaults to sys.argv[1:])

    Returns:
        Parsed arguments namespace

    Raises:
        SystemExit: If validation fails or --help is used
    """
    parser = create_parser()
    parsed = parser.parse_args(args)

    # Validate repo-path exists
    repo_path = Path(parsed.repo_path)
    if not repo_path.exists():
        parser.error(f"Repository path does not exist: {parsed.repo_path}")
    if not repo_path.is_dir():
        parser.error(f"Repository path is not a directory: {parsed.repo_path}")

    # Validate chunk-size and chunk-overlap are positive
    if parsed.chunk_size <= 0:
        parser.error(f"Chunk size must be positive, got: {parsed.chunk_size}")
    if parsed.chunk_overlap < 0:
        parser.error(f"Chunk overlap must be non-negative, got: {parsed.chunk_overlap}")
    if parsed.chunk_overlap >= parsed.chunk_size:
        parser.error(
            f"Chunk overlap ({parsed.chunk_overlap}) must be less than chunk size ({parsed.chunk_size})"
        )

    # Validate batch-size is positive
    if parsed.batch_size <= 0:
        parser.error(f"Batch size must be positive, got: {parsed.batch_size}")

    return parsed


def setup_logging(verbose: bool) -> None:
    """
    Configure logging based on verbosity.

    Args:
        verbose: If True, set INFO level, otherwise WARNING
    """
    level = logging.INFO if verbose else logging.WARNING
    logging.basicConfig(
        level=level,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # Suppress noisy third-party loggers unless verbose
    if not verbose:
        logging.getLogger("urllib3").setLevel(logging.WARNING)
        logging.getLogger("requests").setLevel(logging.WARNING)
        logging.getLogger("httpx").setLevel(logging.WARNING)


__all__ = ["create_parser", "parse_args", "setup_logging"]
