"""Build an OKF ("Open Knowledge Format") LLM wiki from a code repository.

Reads the repo, extracts the concept skeleton (Tree-sitter), enriches each
concept with DeepSeek into human-readable wiki prose, and writes an OKF bundle
(Markdown + YAML frontmatter + cross-links) to --out-dir. Re-runs are
incremental: unchanged files reuse cached enrichments.

Examples:
  cvg-okf-build --repo-path ./examples/sample-repo --limit 20 --verbose
  cvg-okf-build --repo-path ./my-app --out-dir okf-wiki --dry-run
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

from code_vector_graph.config import (  # noqa: E402
    DEEPSEEK_API_KEY,
    DEEPSEEK_BASE_URL,
    OKF_MODEL_FLASH,
    OKF_MODEL_PRO,
    OKF_OUT_DIR,
)
from code_vector_graph.ingestion.okf import build_skeleton, write_bundle  # noqa: E402
from code_vector_graph.ingestion.okf import cache as okf_cache  # noqa: E402
from code_vector_graph.ingestion.okf.enricher import enrich_all, make_client  # noqa: E402

logger = logging.getLogger(__name__)


def create_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="cvg-okf-build",
        description="Generate an OKF LLM wiki from a JS/TS repository using DeepSeek.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("--repo-path", default=".", help="Repository to document (default: .)")
    p.add_argument("--out-dir", default=OKF_OUT_DIR, help=f"Output bundle directory (default: {OKF_OUT_DIR})")
    p.add_argument("--model-flash", default=OKF_MODEL_FLASH, help=f"Model for concept pages (default: {OKF_MODEL_FLASH})")
    p.add_argument("--model-pro", default=OKF_MODEL_PRO, help=f"Model for the architecture overview (default: {OKF_MODEL_PRO})")
    p.add_argument("--concurrency", type=int, default=6, help="Concurrent enrichment requests (default: 6)")
    p.add_argument("--labels", default=None, help="Comma-separated node labels to enrich (default: File,Class,Function,Method,Interface,TypeAlias)")
    p.add_argument("--exclude-labels", default=None, help="Comma-separated labels to exclude")
    p.add_argument("--repo-base-url", default=None, help="Base URL for `resource` links, e.g. https://github.com/org/repo/blob/main")
    p.add_argument("--repo-root", default=None, help="Path prefix stripped from `resource` (default: --repo-path)")
    p.add_argument("--limit", type=int, default=None, help="Cap number of concepts (smoke tests)")
    p.add_argument("--force", action="store_true", help="Ignore the incremental cache; re-enrich everything")
    p.add_argument("--dry-run", action="store_true", help="Build skeleton + bundle with metadata-only pages; no API calls")
    p.add_argument("--verbose", action="store_true", help="Verbose logging")
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

    repo_path = args.repo_path
    if not Path(repo_path).is_dir():
        print(f"ERROR: repo path is not a directory: {repo_path}", file=sys.stderr)
        return 1

    labels = [s.strip() for s in args.labels.split(",")] if args.labels else None
    exclude = [s.strip() for s in args.exclude_labels.split(",")] if args.exclude_labels else None

    logger.info("Building skeleton for %s ...", repo_path)
    skeleton = build_skeleton(repo_path, labels=labels, exclude_labels=exclude, limit=args.limit)
    if not skeleton.concept_ids:
        print("No concepts found to document (no supported source files?).", file=sys.stderr)
        return 1

    client = None
    if not args.dry_run:
        try:
            client = make_client(DEEPSEEK_API_KEY, DEEPSEEK_BASE_URL)
        except ValueError as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            return 1

    pre_cache = {} if args.force else okf_cache.load_cache(args.out_dir)
    cached_before = 0
    if not args.force and not args.dry_run:
        for nid in skeleton.concept_ids:
            node = skeleton.nodes.get(nid)
            if node and okf_cache.concept_hash(node) in pre_cache:
                cached_before += 1

    total = len(skeleton.concept_ids)

    def _progress(done: int, n: int) -> None:
        if args.verbose and (done == n or done % 25 == 0):
            logger.info("Enriched %d/%d concepts", done, n)

    logger.info("Enriching %d concepts (dry_run=%s) ...", total, args.dry_run)
    enrichments, overview, cache = enrich_all(
        skeleton,
        client,
        model_flash=args.model_flash,
        model_pro=args.model_pro,
        concurrency=args.concurrency,
        cache=pre_cache,
        force=args.force,
        dry_run=args.dry_run,
        progress=_progress,
    )

    stats = {
        "model_flash": args.model_flash,
        "model_pro": args.model_pro,
        "enriched": total,
        "cached": cached_before,
        "dry_run": args.dry_run,
    }
    result = write_bundle(
        args.out_dir,
        skeleton,
        enrichments,
        overview,
        repo_base_url=args.repo_base_url,
        repo_root=args.repo_root or repo_path,
        stats=stats,
    )

    if not args.dry_run:
        okf_cache.save_cache(args.out_dir, cache)

    print("\nOKF wiki build complete")
    print(f"  Bundle:     {args.out_dir}")
    print(f"  Files:      {len(skeleton.files)}")
    print(f"  Concepts:   {total}  (pages written: {result['pages']})")
    if not args.dry_run:
        print(f"  Reused cache: {cached_before}  |  Newly enriched: {total - cached_before}")
    print("  By type:    " + ", ".join(f"{k}={v}" for k, v in sorted(result["counts"].items())))
    if args.dry_run:
        print("  (dry run — metadata-only pages, no DeepSeek calls)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
