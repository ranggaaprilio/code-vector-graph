"""Code Vector Graph - Main pipeline orchestration."""

import gc
import logging
import sys
from pathlib import Path

import torch
from dotenv import load_dotenv

load_dotenv()

from src.chunker import chunk_text
from src.cli import parse_args, setup_logging
from src.config import (
    NEO4J_PASSWORD,
    NEO4J_URI,
    NEO4J_USER,
    get_model_config,
)
from src.embedder import create_embedder
from src.glossary import (
    build_glossary_graph,
    extract_comment_glossary,
    load_manual_glossary,
)
from src.graph_extractor import extract_graph_entities
from src.graph_store import GraphStore
from src.parser import extract_ast_metadata, parse_file
from src.scanner import discover_files
from src.store import VectorStore, get_collection_name

logger = logging.getLogger(__name__)

# Batch size for file processing to control memory usage
FILE_BATCH_SIZE = 50


def check_embedder_health(embedder) -> bool:
    """Check embedder health and fail fast with clear error if unreachable."""
    logger.info("Checking embedder health...")
    if not embedder.check_health():
        logger.error("Embedder health check failed")
        print(
            "ERROR: Embedder is not available.",
            file=sys.stderr,
        )
        return False
    logger.info("Embedder health check passed")
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
        print(
            "  1. Qdrant is running (docker run -p 6333:6333 qdrant/qdrant)",
            file=sys.stderr,
        )
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
        "files_graphed": 0,
        "total_chunks": 0,
        "chunks_embedded": 0,
        "chunks_stored": 0,
        "nodes_created": 0,
        "relationships_created": 0,
        "glossary_entries": 0,
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

    model_config = get_model_config(args.model)
    dimensions = model_config["dimensions"]
    collection_name = get_collection_name(args.collection_name, "huggingface", model=model_config["model_name"])
    tokenizer_name = model_config["tokenizer_name"]

    # Step 2: Initialize components (skip in dry-run mode to save memory)
    embedder = None
    store = None
    graph_store = None
    manual_glossary_entries = []

    if not args.dry_run:
        embedder = create_embedder(model_id=args.model)
        store = VectorStore(
            collection_name=collection_name,
            qdrant_url=args.qdrant_url,
            embedding_dimensions=dimensions,
        )

        if not embedder.check_health():
            logger.error("Embedder health check failed")
            print("ERROR: HuggingFace embedder is not available.", file=sys.stderr)
            sys.exit(1)
        check_qdrant_health(store)
        store.create_collection()

        if not args.no_graph:
            graph_store = GraphStore(
                uri=args.neo4j_uri or NEO4J_URI,
                user=args.neo4j_user or NEO4J_USER,
                password=args.neo4j_password or NEO4J_PASSWORD,
            )
            if not graph_store.check_health():
                logger.warning("Neo4j unavailable, continuing without graph")
                graph_store.close()
                graph_store = None
            else:
                logger.info("Neo4j health check passed")
                graph_store.create_constraints()
        else:
            logger.info("Graph ingestion disabled via --no-graph")

        manual_glossary_entries = load_manual_glossary(
            getattr(args, "glossary_file", "glossary.yml"),
            args.repo_path,
        )
        if manual_glossary_entries:
            logger.info(f"Loaded {len(manual_glossary_entries)} manual glossary entries")
    else:
        logger.info("Dry-run mode: skipping component initialization and health checks")

    # Step 3: Parse and process files in batches to control memory usage
    total_files = len(files)
    total_chunks_created = 0

    for batch_start in range(0, total_files, FILE_BATCH_SIZE):
        batch_end = min(batch_start + FILE_BATCH_SIZE, total_files)
        file_batch = files[batch_start:batch_end]

        logger.info(
            f"Processing file batch {batch_start // FILE_BATCH_SIZE + 1}/{(total_files + FILE_BATCH_SIZE - 1) // FILE_BATCH_SIZE} ({batch_start + 1}-{batch_end}/{total_files})"
        )

        # Accumulate chunks for this batch only
        batch_chunks = []
        batch_graph_data = []
        batch_code_chunks_created = 0

        for file_info in file_batch:
            file_path = file_info["path"]
            grammar = file_info["grammar"]
            language = file_info["language"]
            file_hash = file_info.get("file_hash", "")

            logger.info(f"[1/4] Parsing file: {file_path}")

            # Parse file
            parsed = parse_file(file_path, grammar)
            if parsed is None:
                logger.warning(f"Failed to parse file: {file_path}")
                stats["files_failed"] += 1
                continue

            logger.info(f"[1/4] Parsing complete: {file_path}")
            stats["files_parsed"] += 1

            # Extract AST metadata (if parsing succeeded)
            ast_metadata = extract_ast_metadata(
                parsed.get("tree"), parsed.get("source_bytes")
            )
            graph_data = None
            if store is not None:
                graph_data = extract_graph_entities(
                    parsed["tree"],
                    parsed["source_bytes"],
                    file_path,
                    language,
                    file_hash,
                )
                comment_glossary_entries = extract_comment_glossary(
                    parsed["tree"],
                    parsed["source_bytes"],
                    file_path,
                    graph_data,
                )
                glossary_nodes, glossary_relationships, glossary_chunks = build_glossary_graph(
                    graph_data,
                    file_path,
                    language,
                    manual_entries=manual_glossary_entries,
                    comment_entries=comment_glossary_entries,
                )
                if glossary_nodes:
                    graph_data["nodes"].extend(glossary_nodes)
                    graph_data["relationships"].extend(glossary_relationships)
                    stats["glossary_entries"] += len(glossary_nodes)
            else:
                glossary_chunks = []

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
                tokenizer_name=tokenizer_name,
            )

            # Flatten metadata and add text_content field for storage
            chunk_nodes = []
            for chunk in chunks:
                metadata = chunk.pop("metadata", {})
                chunk.update(metadata)
                chunk["text_content"] = chunk["text"]

                if graph_data is not None:
                    chunk_id = store._generate_deterministic_id(
                        chunk.get("file_path", ""),
                        chunk.get("chunk_index", 0),
                        chunk.get("file_hash", ""),
                    )
                    chunk_node = {
                        "label": "Chunk",
                        "id": chunk_id,
                        "properties": {
                            "qdrant_id": chunk_id,
                            "file_path": chunk.get("file_path", ""),
                            "start_line": chunk.get("start_line", 0),
                            "end_line": chunk.get("end_line", 0),
                            "chunk_index": chunk.get("chunk_index", 0),
                            "total_chunks": chunk.get("total_chunks", 0),
                            "function_name": chunk.get("function_name"),
                            "class_name": chunk.get("class_name"),
                            "parent_function": chunk.get("parent_function"),
                            "imports": chunk.get("imports", []),
                            "exports": chunk.get("exports", []),
                            "symbols_defined": chunk.get("symbols_defined", []),
                            "call_sites": chunk.get("call_sites", []),
                            "is_exported": chunk.get("is_exported", False),
                            "visibility": chunk.get("visibility"),
                            "nesting_depth": chunk.get("nesting_depth", 0),
                            "token_count": chunk.get("token_count", 0),
                            "decorators": chunk.get("decorators", []),
                            "file_hash": chunk.get("file_hash", ""),
                        }
                    }
                    chunk_nodes.append(chunk_node)

            if graph_data is not None and chunk_nodes:
                graph_data["nodes"].extend(chunk_nodes)
                for chunk in chunks:
                    chunk["graph_nodes"] = []
                    chunk["graph_relationships"] = []
                chunks[0]["graph_nodes"] = graph_data["nodes"]
                chunks[0]["graph_relationships"] = graph_data["relationships"]

                if graph_store:
                    batch_graph_data.append(graph_data)
                    stats["files_graphed"] += 1

            batch_code_chunks_created += len(chunks)
            batch_chunks.extend(chunks)
            batch_chunks.extend(glossary_chunks)

            # Free parsed dict to release stripped_text memory
            parsed.clear()
            logger.debug(f"Created {len(chunks)} chunks from {file_path}")

        total_chunks_created += batch_code_chunks_created
        logger.info(
            f"Created {batch_code_chunks_created} code chunks from this batch (total: {total_chunks_created})"
        )

        # Step 4: Skip embedding/storage in dry-run mode
        if args.dry_run:
            # Clear batch chunks to free memory
            batch_chunks.clear()
            continue

        if graph_store and batch_graph_data:
            logger.info(f"Graph extraction complete for {len(batch_graph_data)} files")

        # Stream embeddings to Qdrant in sub-batches to cap memory usage
        if batch_chunks:
            total_sub_batches = (
                len(batch_chunks) + args.batch_size - 1
            ) // args.batch_size
            logger.info(
                f"Streaming {len(batch_chunks)} chunks through {total_sub_batches} embedding sub-batches..."
            )
            for sub_idx in range(total_sub_batches):
                sub_start = sub_idx * args.batch_size
                sub_end = min(sub_start + args.batch_size, len(batch_chunks))
                sub_batch = batch_chunks[sub_start:sub_end]

                logger.info(
                    f"Embedding sub-batch {sub_idx + 1}/{total_sub_batches} ({len(sub_batch)} chunks)..."
                )
                embedded_sub = embedder.embed_chunks(
                    sub_batch, batch_size=args.batch_size
                )
                stats["chunks_embedded"] += len(embedded_sub)

                if embedded_sub:
                    logger.info(
                        f"Storing sub-batch {sub_idx + 1}/{total_sub_batches} in Qdrant..."
                    )
                    point_ids = store.upsert_chunks(embedded_sub)
                    stats["chunks_stored"] += len(point_ids)
                    logger.info(f"Successfully stored {len(point_ids)} chunks")

                del embedded_sub
                del sub_batch
                gc.collect()
                if torch.backends.mps.is_available():
                    torch.mps.empty_cache()
                logger.info(
                    f"Freed memory after sub-batch {sub_idx + 1}/{total_sub_batches}"
                )

        if graph_store and batch_graph_data:
            logger.info(
                f"Upserting graph data for {len(batch_graph_data)} files to Neo4j..."
            )
            for graph_data in batch_graph_data:
                node_counts = graph_store.upsert_nodes(graph_data["nodes"])
                relationship_counts = graph_store.upsert_relationships(graph_data["relationships"])
                stats["nodes_created"] += node_counts["nodes_created"]
                stats["relationships_created"] += relationship_counts["relationships_created"]

            for gd in batch_graph_data:
                del gd
            del batch_graph_data
            gc.collect()
            logger.info("Graph ingestion complete for this batch")

        batch_chunks.clear()
        del batch_chunks
        gc.collect()

    stats["total_chunks"] = total_chunks_created
    logger.info(
        f"Created {total_chunks_created} total chunks from {stats['files_parsed']} files"
    )

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
        print("No embeddings or graphs were generated or stored.")
        print("Run without --dry-run to perform full embedding.")
        print("=" * 50)

        return stats

    if graph_store:
        graph_store.close()

    logger.info("Pipeline completed successfully")
    print(f"\nPipeline Summary:")
    print(f"  Files processed: {stats['files_parsed']}/{stats['files_found']}")
    print(f"  Chunks embedded: {stats['chunks_embedded']}")
    print(f"  Chunks stored:   {stats['chunks_stored']}")
    if stats["files_graphed"] > 0:
        print(f"  Files graphed:   {stats['files_graphed']}")
        print(f"  Nodes created:   {stats['nodes_created']}")
        print(f"  Relationships:   {stats['relationships_created']}")
    if stats["glossary_entries"] > 0:
        print(f"  Glossary entries: {stats['glossary_entries']}")

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