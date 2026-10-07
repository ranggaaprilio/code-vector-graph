"""Generate feature-level (business-logic) documentation for a repository.

Discovers business features across the repo's files — a two-stage LLM
process: group files into features, then write one validated Markdown page
per feature (see `ingestion/okf/features/`) — syncs the result into Neo4j +
Qdrant, and exports a bundle. Complements `cvg-okf-build`/`cvg-okf-sync`
(per-symbol wiki pages): this generates the coarser, business-facing layer.

A human edit to a Feature page (made via the dashboard) is never overwritten
by a later run; if the underlying code has changed since the edit, the page
is instead marked `stale`.

Examples:
  cvg-docs-build --repo-path ./my-app --dry-run --no-neo4j --no-qdrant --verbose
  cvg-docs-build --repo-path ./my-app --app-name my-app --collection-name code_chunks --verbose
  cvg-docs-build --repo-path ./my-app --only checkout,user-auth --verbose
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

from code_vector_graph.config import (  # noqa: E402
    CVG_DOCS_BUNDLE_DIR,
    CVG_DOCS_LANGUAGE,
    CVG_REPOS_ROOT,
    DEFAULT_COLLECTION_NAME,
    DEFAULT_MODEL_ID,
    DEFAULT_QDRANT_URL,
    MODEL_CONFIGS,
    NEO4J_PASSWORD,
    NEO4J_URI,
    NEO4J_USER,
    OKF_FEATURES_MODEL,
    get_model_config,
)
from code_vector_graph.ingestion.okf.enricher import make_client  # noqa: E402
from code_vector_graph.ingestion.okf.features import (  # noqa: E402
    FeatureBuildDeps,
    FeatureBuildRequest,
    build_feature_docs,
)
from code_vector_graph.repos import resolve_repo_identity  # noqa: E402

logger = logging.getLogger(__name__)


def create_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="cvg-docs-build",
        description="Generate feature-level (business-logic) documentation for a repository.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("--repo-path", default=".", help="Repository to document (default: .)")
    p.add_argument("--repo-name", default=None, help="Repository name (default: basename of --repo-path)")
    p.add_argument("--app-name", default=None,
                   help="Application the repository belongs to (default: derived from CVG_REPOS_ROOT, else the repo name)")
    p.add_argument("--bundle-dir", default=CVG_DOCS_BUNDLE_DIR,
                   help=f"OKF bundle directory to export into (default: {CVG_DOCS_BUNDLE_DIR})")
    p.add_argument("--model-map", default=OKF_FEATURES_MODEL,
                   help=f"Model for the feature-discovery map/merge calls (default: {OKF_FEATURES_MODEL})")
    p.add_argument("--model-doc", default=OKF_FEATURES_MODEL,
                   help=f"Model for per-feature doc generation (default: {OKF_FEATURES_MODEL})")
    p.add_argument("--language", default=CVG_DOCS_LANGUAGE, help=f"Prose language (default: {CVG_DOCS_LANGUAGE})")
    p.add_argument("--concurrency", type=int, default=4, help="Concurrent doc-generation requests (default: 4)")
    p.add_argument("--force", action="store_true", help="Ignore the doc cache; regenerate every LLM-authored feature")
    p.add_argument("--only", default=None, help="Comma-separated feature slugs to (re)generate; others are left untouched")
    p.add_argument("--dry-run", action="store_true",
                   help="Structural feature map + fallback pages written to the bundle; no LLM calls, no DB writes")
    p.add_argument("--no-neo4j", action="store_true", help="Skip the Neo4j sync (also disables human-edit preservation)")
    p.add_argument("--no-qdrant", action="store_true", help="Skip the Qdrant sync")
    p.add_argument("--model", default=DEFAULT_MODEL_ID, choices=list(MODEL_CONFIGS.keys()),
                   help=f"Embedding model (default: {DEFAULT_MODEL_ID})")
    p.add_argument("--qdrant-url", default=DEFAULT_QDRANT_URL, help=f"Qdrant URL (default: {DEFAULT_QDRANT_URL})")
    p.add_argument("--collection-name", default=DEFAULT_COLLECTION_NAME,
                   help=f"Qdrant collection base name — must match the code collection (default: {DEFAULT_COLLECTION_NAME})")
    p.add_argument("--collection-name-is-final", action="store_true",
                   help="Use --collection-name verbatim (skip model/dim suffixing)")
    p.add_argument("--neo4j-uri", default=NEO4J_URI)
    p.add_argument("--neo4j-user", default=NEO4J_USER)
    p.add_argument("--neo4j-password", default=NEO4J_PASSWORD)
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

    if not Path(args.repo_path).is_dir():
        print(f"ERROR: repo path is not a directory: {args.repo_path}", file=sys.stderr)
        return 1

    identity = resolve_repo_identity(args.repo_path, args.repo_name, args.app_name, CVG_REPOS_ROOT)

    client = None
    if not args.dry_run:
        try:
            client = make_client()
        except ValueError as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            return 1

    graph_store = None
    if not args.no_neo4j:
        from code_vector_graph.stores.graph_store import GraphStore

        graph_store = GraphStore(uri=args.neo4j_uri, user=args.neo4j_user, password=args.neo4j_password)
        if not graph_store.check_health():
            print("ERROR: Neo4j is not reachable. Start it (docker compose up -d) or use --no-neo4j.", file=sys.stderr)
            return 1

    vector_store = None
    embedder = None
    tokenizer_name = None
    if not args.no_qdrant:
        from code_vector_graph.embeddings.embedder import create_embedder
        from code_vector_graph.stores.vector_store import VectorStore, get_collection_name

        model_config = get_model_config(args.model)
        tokenizer_name = model_config["tokenizer_name"]
        collection = (
            args.collection_name
            if args.collection_name_is_final
            else get_collection_name(args.collection_name, "huggingface", model=model_config["model_name"])
        )
        vector_store = VectorStore(
            collection_name=collection, qdrant_url=args.qdrant_url, embedding_dimensions=model_config["dimensions"]
        )
        if not vector_store.check_health():
            print("ERROR: Qdrant is not reachable. Start it (docker compose up -d) or use --no-qdrant.", file=sys.stderr)
            return 1
        embedder = create_embedder(model_id=args.model)
        if not embedder.check_health():
            print("ERROR: embedder is not available.", file=sys.stderr)
            return 1

    only_slugs = [s.strip() for s in args.only.split(",") if s.strip()] if args.only else None

    req = FeatureBuildRequest(
        repo_path=args.repo_path, app=identity.app, repo_name=identity.name, repo_id=identity.id,
        bundle_dir=args.bundle_dir, language=args.language, model_map=args.model_map, model_doc=args.model_doc,
        concurrency=args.concurrency, force=args.force, dry_run=args.dry_run, only_slugs=only_slugs,
    )
    deps = FeatureBuildDeps(
        llm_client=client, graph_store=graph_store, vector_store=vector_store,
        embedder=embedder, tokenizer_name=tokenizer_name,
    )

    try:
        result = build_feature_docs(req, deps)
    finally:
        if graph_store is not None:
            graph_store.close()

    print("\nFeature docs build complete")
    print(f"  App/repo:      {identity.app} / {identity.name}")
    print(f"  Bundle:        {args.bundle_dir}")
    print(f"  Features:      {result.features}")
    print(f"  Generated:     {result.generated}  |  Cached: {result.cached}  |  Kept (human): {result.kept_human}")
    print(f"  Stale:         {result.stale}  |  Deleted (orphaned): {result.deleted}")
    if result.needs_reembed:
        print(f"  Needs re-embed: {result.needs_reembed} (no embedder available this run)")
    if args.dry_run:
        print("  (dry run — no LLM calls, no DB writes; bundle preview only)")
    for w in result.warnings:
        print(f"  WARNING: {w}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
