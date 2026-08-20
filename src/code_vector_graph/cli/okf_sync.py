"""Sync an OKF wiki bundle into Qdrant + Neo4j (Phase 2).

Reads the OKF bundle produced by `cvg-okf-build` and pushes it into the
stores so the enriched wiki is searchable and connected to the code graph:
- Qdrant: embeds each page's prose (tagged source="okf_wiki").
- Neo4j: a WikiPage node per concept, DOCUMENTS-> the code node it documents, and
  REFERENCES-> other wiki pages (the LLM's "Related" links).

Examples:
  cvg-okf-sync --bundle okf-wiki --verbose
  cvg-okf-sync --bundle okf-wiki --no-qdrant       # graph only
  cvg-okf-sync --bundle okf-wiki --dry-run         # parse + report
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

from code_vector_graph.config import (  # noqa: E402
    DEFAULT_MODEL_ID,
    DEFAULT_QDRANT_URL,
    MODEL_CONFIGS,
    NEO4J_PASSWORD,
    NEO4J_URI,
    NEO4J_USER,
    get_model_config,
)
from code_vector_graph.ingestion.okf.sync import parse_bundle, sync_neo4j, sync_qdrant  # noqa: E402

logger = logging.getLogger(__name__)

DEFAULT_WIKI_COLLECTION = "okf_wiki"


def create_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="cvg-okf-sync",
        description="Sync an OKF wiki bundle into Qdrant + Neo4j.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("--bundle", default="okf-wiki", help="OKF bundle directory (default: okf-wiki)")
    p.add_argument("--no-qdrant", action="store_true", help="Skip the Qdrant sync")
    p.add_argument("--no-neo4j", action="store_true", help="Skip the Neo4j sync")
    p.add_argument("--model", default=DEFAULT_MODEL_ID, choices=list(MODEL_CONFIGS.keys()),
                   help=f"Embedding model (default: {DEFAULT_MODEL_ID})")
    p.add_argument("--qdrant-url", default=DEFAULT_QDRANT_URL, help=f"Qdrant URL (default: {DEFAULT_QDRANT_URL})")
    p.add_argument("--collection-name", default=DEFAULT_WIKI_COLLECTION,
                   help=f"Qdrant collection base name (default: {DEFAULT_WIKI_COLLECTION})")
    p.add_argument("--collection-name-is-final", action="store_true",
                   help="Use --collection-name verbatim (skip model/dim suffixing)")
    p.add_argument("--neo4j-uri", default=NEO4J_URI)
    p.add_argument("--neo4j-user", default=NEO4J_USER)
    p.add_argument("--neo4j-password", default=NEO4J_PASSWORD)
    p.add_argument("--batch-size", type=int, default=64, help="Embedding batch size (default: 64)")
    p.add_argument("--dry-run", action="store_true", help="Parse bundle and report; no writes")
    p.add_argument("--verbose", action="store_true")
    return p


def _setup_logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.INFO if verbose else logging.WARNING,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        datefmt="%H:%M:%S",
    )


def main(argv: list[str] | None = None) -> int:
    args = create_parser().parse_args(argv)
    _setup_logging(args.verbose)

    if not Path(args.bundle).is_dir():
        print(f"ERROR: bundle directory not found: {args.bundle}", file=sys.stderr)
        return 1

    concepts = parse_bundle(args.bundle)
    if not concepts:
        print(f"No concept pages found in {args.bundle} (is it an OKF bundle?).", file=sys.stderr)
        return 1

    related = sum(len(c.get("related_paths", [])) for c in concepts)
    print(f"Parsed {len(concepts)} concept pages ({related} related links).")

    if args.dry_run:
        with_id = sum(1 for c in concepts if c.get("concept_id"))
        print("Dry run — no writes.")
        print(f"  Would upsert {with_id} WikiPage nodes + DOCUMENTS edges to Neo4j.")
        print(f"  Would embed prose for {len(concepts)} concepts to Qdrant.")
        return 0

    # --- Neo4j ---
    if not args.no_neo4j:
        from code_vector_graph.stores.graph_store import GraphStore

        graph_store = GraphStore(uri=args.neo4j_uri, user=args.neo4j_user, password=args.neo4j_password)
        try:
            if not graph_store.check_health():
                print("ERROR: Neo4j is not reachable. Start it (docker compose up -d) or use --no-neo4j.", file=sys.stderr)
                return 1
            stats = sync_neo4j(concepts, graph_store)
            print(
                f"Neo4j: {stats['wiki_pages']} WikiPage nodes "
                f"({stats['nodes_created']} new), "
                f"{stats['documents_edges']} DOCUMENTS + {stats['references_edges']} REFERENCES edges "
                f"({stats['relationships_created']} new)."
            )
        finally:
            graph_store.close()

    # --- Qdrant ---
    if not args.no_qdrant:
        from code_vector_graph.embeddings.embedder import create_embedder
        from code_vector_graph.stores.vector_store import VectorStore, get_collection_name

        model_config = get_model_config(args.model)
        if args.collection_name_is_final:
            collection = args.collection_name
        else:
            collection = get_collection_name(args.collection_name, "huggingface", model=model_config["model_name"])

        store = VectorStore(
            collection_name=collection,
            qdrant_url=args.qdrant_url,
            embedding_dimensions=model_config["dimensions"],
        )
        if not store.check_health():
            print("ERROR: Qdrant is not reachable. Start it (docker compose up -d) or use --no-qdrant.", file=sys.stderr)
            return 1

        embedder = create_embedder(model_id=args.model)
        if not embedder.check_health():
            print("ERROR: embedder is not available.", file=sys.stderr)
            return 1

        stats = sync_qdrant(concepts, embedder, store, tokenizer_name=model_config["tokenizer_name"], batch_size=args.batch_size)
        print(f"Qdrant: embedded {stats['chunks']} prose chunks -> collection '{collection}' ({stats['stored']} stored).")

    print("\nOKF sync complete.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
