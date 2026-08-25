"""`cvg-ingest` — index a repository into Qdrant + Neo4j."""

import argparse
import logging
import sys
from pathlib import Path

from dotenv import load_dotenv

# .env must load before config is imported: config resolves EMBEDDING_MODEL_ID and
# the other overrides from the environment at import time.
load_dotenv()

from code_vector_graph.config import (  # noqa: E402
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
        prog="cvg-ingest",
        description="Embed JS/TS code into Qdrant using Tree-sitter and HuggingFace transformers.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s --repo-path ./my-project
  %(prog)s --repo-path ./my-project --dry-run --verbose
  %(prog)s --repo-path ./my-project --qdrant-url http://localhost:6333
  %(prog)s --repo-path ~/Repository/onebid/backend/api --repo-name api --app-name onebid
        """.strip(),
    )

    parser.add_argument(
        "--repo-path",
        type=str,
        required=True,
        help="Path to repository to process (required)",
    )

    parser.add_argument(
        "--repo-name",
        type=str,
        default=None,
        help=(
            "Repository name recorded on every chunk / File node "
            "(default: basename of the resolved --repo-path)"
        ),
    )

    parser.add_argument(
        "--app-name",
        type=str,
        default=None,
        help=(
            "Application the repository belongs to (default: first path component "
            "below CVG_REPOS_ROOT when set, otherwise the repo name)"
        ),
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


def main() -> int:
    """Entry point for `cvg-ingest`.

    Returns:
        Exit code (0 for success, 1 for error)
    """
    from code_vector_graph.ingestion.pipeline import run_pipeline
    from code_vector_graph.logging_setup import setup_logging

    try:
        args = parse_args()
        setup_logging(args.verbose)

        logger.debug(f"Arguments: {args}")

        run_pipeline(args)

        return 0

    except KeyboardInterrupt:
        print("\n\nOperation cancelled by user", file=sys.stderr)
        return 130

    except Exception as e:
        logger.exception("Unexpected error occurred")
        print(f"\nERROR: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())


__all__ = ["create_parser", "parse_args", "main"]
