"""Code Vector Graph - Main pipeline orchestration."""

import gc
import logging
import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

from src.chunker import chunk_text
from src.cli import parse_args, setup_logging
from src.config import EMBEDDING_PREFIX, EMBEDDING_PROVIDERS
from src.embedder import create_embedder
from src.parser import parse_file, extract_ast_metadata
from src.scanner import discover_files
from src.store import VectorStore, get_collection_name

logger = logging.getLogger(__name__)

# Batch size for file processing to control memory usage
FILE_BATCH_SIZE = 50


def check_ollama_health(embedder) -> bool:
    """
    Check Ollama health and fail fast with clear error if unreachable.

    Args:
        embedder: Configured embedder instance

    Returns:
        True if healthy

    Raises:
        SystemExit: If Ollama is unreachable or model is unavailable
    """
    logger.info("Checking Ollama health...")

    if not embedder.check_health():
        logger.error("Ollama health check failed")
        print(
            "ERROR: Cannot connect to Ollama or model is not available.",
            file=sys.stderr,
        )
        print(f"  URL: {embedder.base_url}", file=sys.stderr)
        print(f"  Model: {embedder.model}", file=sys.stderr)
        print("\nPlease ensure:", file=sys.stderr)
        print("  1. Ollama is running (ollama serve)", file=sys.stderr)
        print(f"  2. Model '{embedder.model}' is pulled (ollama pull {embedder.model})", file=sys.stderr)
        sys.exit(1)

    logger.info("Ollama health check passed")
    return True


def check_qdrant_health(store: VectorStore) -> bool:
    """
    Check Qdrant health and fail fast with clear error if unreachable.

    Args:
        store: Configured VectorStore instance

    Returns:
        True if healthy

    Raises:
        SystemExit: If Qdrant is unreachable
    """
    logger.info("Checking Qdrant health...")

    if not store.check_health():
        logger.error("Qdrant health check failed")
        print(
            "ERROR: Cannot connect to Qdrant server.",
            file=sys.stderr,
        )
        print(f"  URL: {store.client}", file=sys.stderr)
        print("\nPlease ensure:", file=sys.stderr)
        print("  1. Qdrant is running (docker run -p 6333:6333 qdrant/qdrant)", file=sys.stderr)
        sys.exit(1)

    logger.info("Qdrant health check passed")
    return True


def run_pipeline(args) -> dict:
    """
    Run the full embedding pipeline.

    Args:
        args: Parsed CLI arguments

    Returns:
        Dictionary with pipeline statistics
    """
    stats = {
        "files_found": 0,
        "files_parsed": 0,
        "files_failed": 0,
        "total_chunks": 0,
        "chunks_embedded": 0,
        "chunks_stored": 0,
    }

    logger.info(f"Starting pipeline for repository: {args.repo_path}")

    # Step 1: Discover files
    logger.info("Discovering files...")
    files = discover_files(args.repo_path)
    stats["files_found"] = len(files)
    logger.info(f"Found {len(files)} supported files")

    if not files:
        logger.warning("No files found to process")
        return stats

    # Get dimensions for the selected provider
    dimensions = EMBEDDING_PROVIDERS[args.embedding_provider]["dimensions"]

    # Generate dynamic collection name
    collection_name = get_collection_name(args.collection_name, args.embedding_provider, args.model)

    # Step 2: Initialize components (skip in dry-run mode to save memory)
    embedder = None
    store = None

    if not args.dry_run:
        embedder_kwargs = {}
        if args.embedding_provider == "ollama":
            embedder_kwargs["model"] = args.model
            embedder_kwargs["base_url"] = args.ollama_url
        embedder = create_embedder(args.embedding_provider, **embedder_kwargs)
        store = VectorStore(
            collection_name=collection_name,
            qdrant_url=args.qdrant_url,
            embedding_dimensions=dimensions,
        )

        # Health checks for external services
        if args.embedding_provider == "ollama":
            check_ollama_health(embedder)
        check_qdrant_health(store)
        store.create_collection()
    else:
        logger.info("Dry-run mode: skipping component initialization and health checks")

    # Step 3: Parse and process files in batches to control memory usage
    total_files = len(files)
    total_chunks_created = 0

    for batch_start in range(0, total_files, FILE_BATCH_SIZE):
        batch_end = min(batch_start + FILE_BATCH_SIZE, total_files)
        file_batch = files[batch_start:batch_end]

        logger.info(f"Processing file batch {batch_start // FILE_BATCH_SIZE + 1}/{(total_files + FILE_BATCH_SIZE - 1) // FILE_BATCH_SIZE} ({batch_start + 1}-{batch_end}/{total_files})")

        # Accumulate chunks for this batch only
        batch_chunks = []

        for file_info in file_batch:
            file_path = file_info["path"]
            grammar = file_info["grammar"]
            language = file_info["language"]
            file_hash = file_info.get("file_hash", "")

            logger.debug(f"Processing file: {file_path}")

            # Parse file
            parsed = parse_file(file_path, grammar)
            if parsed is None:
                logger.warning(f"Failed to parse file: {file_path}")
                stats["files_failed"] += 1
                continue

            stats["files_parsed"] += 1

            # Extract AST metadata (if parsing succeeded)
            ast_metadata = extract_ast_metadata(parsed.get("tree"), parsed.get("source_bytes"))

            # Free large objects immediately after metadata extraction
            parsed.pop("source_bytes", None)
            parsed.pop("tree", None)

            # Chunk the parsed text, wiring in AST metadata to chunks
            chunks = chunk_text(
                text=parsed["stripped_text"],
                start_line=1,
                end_line=parsed["stripped_line_count"],
                chunk_size=args.chunk_size,
                chunk_overlap=args.chunk_overlap,
                file_path=file_path,
                language=language,
                node_type=ast_metadata.get("node_type"),
                class_name=ast_metadata.get("class_name"),
                parent_function=ast_metadata.get("parent_function"),
                imports=ast_metadata.get("imports"),
                exports=ast_metadata.get("exports"),
                symbols_defined=ast_metadata.get("symbols_defined"),
                call_sites=ast_metadata.get("call_sites"),
                is_exported=ast_metadata.get("is_exported"),
                visibility=ast_metadata.get("visibility"),
                decorators=ast_metadata.get("decorators"),
                file_hash=file_hash,
            )

            # Flatten metadata and add text_content field for storage
            for chunk in chunks:
                metadata = chunk.pop("metadata", {})
                chunk.update(metadata)
                chunk["text_content"] = chunk["text"]

            batch_chunks.extend(chunks)
            
            # Free parsed dict to release stripped_text memory
            parsed.clear()
            logger.debug(f"Created {len(chunks)} chunks from {file_path}")

        total_chunks_created += len(batch_chunks)
        logger.info(f"Created {len(batch_chunks)} chunks from this batch (total: {total_chunks_created})")

        # Step 4: Skip embedding/storage in dry-run mode
        if args.dry_run:
            # Clear batch chunks to free memory
            batch_chunks.clear()
            continue

        # Step 5: Embed and store this batch immediately
        if batch_chunks:
            logger.info(f"Embedding {len(batch_chunks)} chunks from batch (batch size: {args.batch_size})...")
            embedded_chunks = embedder.embed_chunks(batch_chunks, batch_size=args.batch_size)
            stats["chunks_embedded"] += len(embedded_chunks)
            logger.info(f"Successfully embedded {len(embedded_chunks)} chunks from this batch")

            # Step 6: Store chunks in Qdrant
            if embedded_chunks:
                logger.info(f"Storing {len(embedded_chunks)} chunks in Qdrant...")
                point_ids = store.upsert_chunks(embedded_chunks)
                stats["chunks_stored"] += len(point_ids)
                logger.info(f"Successfully stored {len(point_ids)} chunks")

        # Clear batch chunks and trigger garbage collection
        batch_chunks.clear()
        gc.collect()

    stats["total_chunks"] = total_chunks_created
    logger.info(f"Created {total_chunks_created} total chunks from {stats['files_parsed']} files")

    # Dry-run summary
    if args.dry_run:
        avg_chunk_size = 0
        if stats["total_chunks"] > 0:
            avg_chunk_size = 0  # We don't have text sizes in streaming mode

        print("\n" + "=" * 50)
        print("DRY RUN COMPLETE")
        print("=" * 50)
        print(f"Files found:    {stats['files_found']}")
        print(f"Files parsed:   {stats['files_parsed']}")
        print(f"Files failed:   {stats['files_failed']}")
        print(f"Total chunks:   {stats['total_chunks']}")
        print(f"Avg chunk size: {avg_chunk_size} chars")
        print("=" * 50)
        print("No embeddings were generated or stored.")
        print("Run without --dry-run to perform full embedding.")
        print("=" * 50)

        return stats

    # Final summary
    logger.info("Pipeline completed successfully")
    print(f"\nPipeline Summary:")
    print(f"  Files processed: {stats['files_parsed']}/{stats['files_found']}")
    print(f"  Chunks embedded: {stats['chunks_embedded']}")
    print(f"  Chunks stored:   {stats['chunks_stored']}")

    return stats


def main() -> int:
    """
    Main entry point for the CLI.

    Returns:
        Exit code (0 for success, 1 for error)
    """
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
