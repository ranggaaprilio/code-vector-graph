"""`cvg-backfill-repo` — stamp app/repo identity onto data indexed before Phase 4.

Derives the application/repository layout from the file paths already in Qdrant
(and Neo4j) and writes it back in place — no re-embedding, no re-parsing. Safe to
re-run: every step is guarded by `repo IS NULL`.

Examples:
  cvg-backfill-repo --dry-run --repos-root ~/Repository
  cvg-backfill-repo --repos-root ~/Repository
  cvg-backfill-repo --app onebid=backend_nodejs_global_tnlm,backend_nodejs_data_sync_onebid
  cvg-backfill-repo --map global_tnlm=/Users/me/Repository/onebid/backend/backend_nodejs_global_tnlm
  cvg-backfill-repo --no-neo4j --wiki-repo backend_nodejs_global_tnlm
"""

from __future__ import annotations

import argparse
import logging
import sys

from dotenv import load_dotenv

load_dotenv()

from code_vector_graph.config import (  # noqa: E402
    CVG_APP_MAP,
    CVG_REPO_MAP,
    CVG_REPOS_ROOT,
    MODEL_CONFIGS,
    NEO4J_PASSWORD,
    NEO4J_URI,
    NEO4J_USER,
    QDRANT_URL,
    active_base_collection,
    active_collection,
    get_model_config,
)
from code_vector_graph.ingestion.backfill_repo import BackfillOptions, run_backfill  # noqa: E402
from code_vector_graph.repos import parse_json_map  # noqa: E402

logger = logging.getLogger(__name__)


def create_parser() -> argparse.ArgumentParser:
    default_collection, _dims, default_model = active_collection()
    p = argparse.ArgumentParser(
        prog="cvg-backfill-repo",
        description="Backfill application/repository identity onto legacy Qdrant + Neo4j data.",
        epilog=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("--qdrant-url", default=QDRANT_URL, help=f"Qdrant URL (default: {QDRANT_URL})")
    p.add_argument(
        "--collection-name",
        default=active_base_collection(),
        help=f"Base Qdrant collection name (default: {active_base_collection()!r} -> {default_collection!r})",
    )
    p.add_argument(
        "--collection-name-is-final",
        action="store_true",
        help="Use --collection-name verbatim (skip model/dim suffixing)",
    )
    p.add_argument(
        "--model",
        default=default_model,
        choices=list(MODEL_CONFIGS.keys()),
        help=f"Embedding model whose suffix names the collection (default: {default_model})",
    )
    p.add_argument("--neo4j-uri", default=NEO4J_URI, help=f"Neo4j bolt URI (default: {NEO4J_URI})")
    p.add_argument("--neo4j-user", default=NEO4J_USER, help=f"Neo4j user (default: {NEO4J_USER})")
    p.add_argument("--neo4j-password", default=NEO4J_PASSWORD, help="Neo4j password")
    p.add_argument(
        "--repos-root",
        default=CVG_REPOS_ROOT or None,
        help="Directory whose first child component names the application (default: CVG_REPOS_ROOT)",
    )
    p.add_argument(
        "--map",
        action="append",
        default=[],
        metavar="NAME=ROOT",
        dest="repo_map",
        help="Explicit repository root override; repeatable (merged over CVG_REPO_MAP)",
    )
    p.add_argument(
        "--app",
        action="append",
        default=[],
        metavar="NAME=REPO,REPO",
        dest="app_map",
        help="Explicit application grouping; repeatable (merged over CVG_APP_MAP)",
    )
    p.add_argument(
        "--wiki-repo",
        default=None,
        help="Repository assigned to OKF wiki points that cannot be resolved through Neo4j",
    )
    p.add_argument("--no-qdrant", action="store_true", help="Skip the Qdrant half")
    p.add_argument("--no-neo4j", action="store_true", help="Skip the Neo4j half")
    p.add_argument("--batch-size", type=int, default=500, help="Paths/points per write (default: 500)")
    p.add_argument("--dry-run", action="store_true", help="Print the plan and stop; no writes")
    p.add_argument("--verbose", action="store_true")
    return p


def _setup_logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.INFO if verbose else logging.WARNING,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        datefmt="%H:%M:%S",
    )


def parse_pairs(values: list[str]) -> dict[str, str]:
    """``["a=b", "c=d"]`` -> ``{"a": "b", "c": "d"}``; malformed entries are skipped."""
    out: dict[str, str] = {}
    for raw in values or []:
        key, sep, value = str(raw).partition("=")
        key, value = key.strip(), value.strip()
        if not sep or not key or not value:
            logger.warning("Ignoring malformed NAME=VALUE argument: %r", raw)
            continue
        out[key] = value
    return out


def resolve_repo_map(cli_values: list[str]) -> dict[str, str]:
    """CVG_REPO_MAP (``{name: root}``) with the ``--map`` flags layered on top."""
    merged = {
        str(k): str(v)
        for k, v in parse_json_map(CVG_REPO_MAP).items()
        if isinstance(v, str) and v.strip()
    }
    merged.update(parse_pairs(cli_values))
    return merged


def resolve_app_map(cli_values: list[str]) -> dict[str, list[str]]:
    """CVG_APP_MAP (``{app: [repos]}``) with the ``--app`` flags layered on top."""
    merged: dict[str, list[str]] = {}
    for app, entries in parse_json_map(CVG_APP_MAP).items():
        if isinstance(entries, str):
            entries = [entries]
        merged[str(app)] = [str(e) for e in (entries or []) if isinstance(e, str) and e]
    for app, joined in parse_pairs(cli_values).items():
        merged[app] = [part.strip() for part in joined.split(",") if part.strip()]
    return merged


def resolve_collection(args: argparse.Namespace) -> str:
    if args.collection_name_is_final:
        return args.collection_name
    from code_vector_graph.stores.vector_store import get_collection_name

    model_config = get_model_config(args.model)
    return get_collection_name(args.collection_name, "huggingface", model=model_config["model_name"])


def options_from_args(args: argparse.Namespace) -> BackfillOptions:
    return BackfillOptions(
        collection=resolve_collection(args),
        qdrant_url=args.qdrant_url,
        neo4j_uri=args.neo4j_uri,
        neo4j_user=args.neo4j_user,
        neo4j_password=args.neo4j_password,
        repos_root=args.repos_root or None,
        repo_map=resolve_repo_map(args.repo_map),
        app_map=resolve_app_map(args.app_map),
        wiki_repo=args.wiki_repo,
        no_qdrant=args.no_qdrant,
        no_neo4j=args.no_neo4j,
        batch_size=args.batch_size,
        dry_run=args.dry_run,
    )


def main(argv: list[str] | None = None) -> int:
    args = create_parser().parse_args(argv)
    _setup_logging(args.verbose)

    if args.no_qdrant and args.no_neo4j:
        print("ERROR: --no-qdrant and --no-neo4j together leave nothing to do.", file=sys.stderr)
        return 1

    options = options_from_args(args)
    print(f"Collection: {options.collection}")
    if options.repos_root:
        print(f"Repos root: {options.repos_root}")

    try:
        summary = run_backfill(options)
    except Exception as exc:
        print(f"ERROR: backfill failed: {exc}", file=sys.stderr)
        logger.exception("backfill failed")
        return 1

    print()
    print(summary["plan_table"])

    if summary["dry_run"]:
        print("\nDry run — no writes.")
        return 0

    if not summary["plan"]:
        print("\nNothing to back-fill.")
        return 0

    q = summary.get("qdrant") or {}
    if q:
        print(
            f"\nQdrant: stamped {q.get('code_files_stamped', 0)} file path(s) "
            f"over {q.get('code_batches', 0)} batch(es) "
            f"({q.get('scanned_points', 0)} legacy points scanned); "
            f"wiki {q.get('wiki_stamped', 0)}/{q.get('wiki_points', 0)} resolved"
            + (f", {q['wiki_unresolved']} unresolved" if q.get("wiki_unresolved") else "")
            + "."
        )
    n = summary.get("neo4j") or {}
    if n:
        print(
            f"Neo4j: {n.get('files', 0)} File node(s), "
            f"{n.get('applications', 0)} Application + {n.get('repositories', 0)} Repository node(s), "
            f"{n.get('repo_file_edges', 0)} CONTAINS edge(s), "
            f"{n.get('chunks', 0)} Chunk(s), {n.get('wiki_pages', 0)} WikiPage(s)."
        )

    for warning in summary.get("warnings") or []:
        print(f"  warning: {warning}", file=sys.stderr)

    print("\nBackfill complete. Refresh the dashboard with POST /api/apps/refresh.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
