"""Backfill application / repository identity onto data indexed before Phase 4.

Everything indexed before the identity fields existed carries no ``app`` /
``repo`` anywhere: Qdrant payloads only have the absolute ``file_path``, and
Neo4j ``File`` nodes only have ``path``. This module derives the identity from
those paths (:mod:`code_vector_graph.repos`) and stamps it in place, **without
re-embedding anything**.

Steps (each guarded by ``repo IS NULL`` so the whole run is idempotent and can be
re-run after a partial failure):

1. Scroll the code points that have no ``repo`` and tally them per ``file_path``.
2. ``cluster_paths`` + ``group_apps`` -> the plan (``app -> repo -> root``).
   ``--dry-run`` stops here after printing the plan.
3. Qdrant code points: create the ``app`` / ``repo`` payload indexes, then
   ``set_payload`` ``{app, repo, repo_root}`` per repo, batched by ``file_path``.
4. Qdrant wiki points (``source="okf_wiki"``): their ``file_path`` is
   repo-relative, so the repo is resolved through Neo4j from their ``symbol_id``
   (the documented code node), falling back to ``--wiki-repo``.
5. Neo4j ``File``: ``app`` / ``repo`` / ``rel_path`` by root prefix.
6. Neo4j ``Application`` / ``Repository`` nodes + their ``CONTAINS`` edges.
7. Neo4j ``Chunk.repo`` through the owning ``File``.
8. Neo4j ``WikiPage.repo`` / ``.app`` through ``DOCUMENTS``.

.. note::

   **Qdrant "no repo" filter.** ``IsNullCondition`` only matches points where the
   key is present and explicitly ``null``; legacy points do not have the key at
   all (that is exactly what makes them legacy). This module therefore filters on
   ``should=[IsNull(repo), IsEmpty(repo)]`` — ``IsEmpty`` covers the
   missing-key case — and additionally skips any point that already came back
   with a truthy ``repo``. Both conditions behave the same way in the local
   (in-memory / on-disk) Qdrant used by the tests; payload indexes are a no-op
   there and emit a ``UserWarning``, which is caught and reported as a warning.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Iterable, Optional

from qdrant_client.models import (
    FieldCondition,
    Filter,
    IsEmptyCondition,
    IsNullCondition,
    MatchAny,
    MatchValue,
    PayloadField,
    PayloadSchemaType,
)

from code_vector_graph.config import (
    NEO4J_PASSWORD,
    NEO4J_URI,
    NEO4J_USER,
    QDRANT_URL,
)
from code_vector_graph.repos import RepoIdentity, cluster_paths, group_apps

logger = logging.getLogger(__name__)

__all__ = [
    "BackfillOptions",
    "PlanEntry",
    "format_plan_table",
    "run_backfill",
]

WIKI_SOURCE = "okf_wiki"
#: Payload fields we need while scrolling (``repo`` doubles as the idempotency guard).
SCROLL_PAYLOAD = ["file_path", "language", "source", "symbol_id", "repo"]
#: Rows touched per Neo4j write transaction inside the write loops.
GRAPH_WRITE_LIMIT = 5000

RESOLVE_WIKI_CYPHER = """
UNWIND $ids AS cid
MATCH (n {id: cid})
OPTIONAL MATCH (f:File)-[:CONTAINS|DEFINES]->(n)
RETURN cid AS cid, coalesce(n.repo, f.repo) AS repo, coalesce(n.path, f.path) AS path
"""

FILE_IDENTITY_CYPHER = """
MATCH (f:File)
WHERE f.repo IS NULL AND f.path STARTS WITH $root_prefix
WITH f LIMIT $limit
SET f.app = $app, f.repo = $repo, f.rel_path = substring(f.path, size($root_prefix))
RETURN count(f) AS n
"""

IDENTITY_NODES_CYPHER = """
MERGE (a:Application {id: $aid})
  SET a.name = $app
MERGE (r:Repository {id: $rid})
  SET r.name = $repo, r.root = $root, r.app = $app,
      r.indexed_at = coalesce(r.indexed_at, $now)
MERGE (a)-[:CONTAINS]->(r)
RETURN r.id AS id
"""

REPO_CONTAINS_CYPHER = """
MATCH (f:File {repo: $repo})
WHERE NOT (:Repository {id: $rid})-[:CONTAINS]->(f)
WITH f LIMIT $limit
MATCH (r:Repository {id: $rid})
MERGE (r)-[:CONTAINS]->(f)
RETURN count(f) AS n
"""

CHUNK_REPO_CYPHER = """
MATCH (f:File {repo: $repo})-[:CONTAINS]->(c:Chunk)
WHERE c.repo IS NULL
WITH c LIMIT $limit
SET c.repo = $repo
RETURN count(c) AS n
"""

WIKI_PAGE_CYPHER = """
MATCH (w:WikiPage)
WHERE w.repo IS NULL
MATCH (w)-[:DOCUMENTS]->(n)
OPTIONAL MATCH (f:File)-[:CONTAINS|DEFINES]->(n)
WITH w, coalesce(n.repo, f.repo) AS repo, coalesce(n.app, f.app) AS app
WHERE repo IS NOT NULL
WITH w, repo, app LIMIT $limit
SET w.repo = repo, w.app = app
RETURN count(w) AS n
"""


# --------------------------------------------------------------------------- #
# Options / plan
# --------------------------------------------------------------------------- #


@dataclass
class BackfillOptions:
    """Everything :func:`run_backfill` needs. Mirrors the ``cvg-backfill-repo`` flags.

    ``client`` / ``graph`` may be injected (tests, or a caller that already holds
    open connections); otherwise they are created from the connection settings
    and closed again before returning.
    """

    collection: str = ""
    qdrant_url: str = QDRANT_URL
    neo4j_uri: str = NEO4J_URI
    neo4j_user: str = NEO4J_USER
    neo4j_password: str = NEO4J_PASSWORD
    repos_root: Optional[str] = None
    repo_map: dict[str, str] = field(default_factory=dict)
    app_map: dict[str, list[str]] = field(default_factory=dict)
    wiki_repo: Optional[str] = None
    no_qdrant: bool = False
    no_neo4j: bool = False
    batch_size: int = 500
    dry_run: bool = False
    client: Any = None
    graph: Any = None


@dataclass
class PlanEntry:
    """One derived repository: which application it belongs to and what it holds."""

    app: str
    repo: str
    root: str
    files: int
    points: int
    file_paths: list[str] = field(default_factory=list)

    @property
    def identity(self) -> RepoIdentity:
        return RepoIdentity(app=self.app, name=self.repo, root=self.root)


def format_plan_table(plan: list[PlanEntry]) -> str:
    """Render the plan as ``app -> repo -> root, files, points``."""
    if not plan:
        return "No legacy points without a `repo` payload — nothing to back-fill."
    headers = ("APP", "REPO", "ROOT", "FILES", "POINTS")
    rows = [(e.app, e.repo, e.root, str(e.files), str(e.points)) for e in plan]
    widths = [max(len(h), *(len(r[i]) for r in rows)) for i, h in enumerate(headers)]
    out = ["  ".join(h.ljust(widths[i]) for i, h in enumerate(headers)).rstrip()]
    out.append("  ".join("-" * w for w in widths))
    for row in rows:
        out.append("  ".join(cell.ljust(widths[i]) for i, cell in enumerate(row)).rstrip())
    out.append(
        f"{len(plan)} repositor{'y' if len(plan) == 1 else 'ies'} in "
        f"{len({e.app for e in plan})} application(s); "
        f"{sum(e.files for e in plan)} files, {sum(e.points for e in plan)} points."
    )
    return "\n".join(out)


# --------------------------------------------------------------------------- #
# Small helpers
# --------------------------------------------------------------------------- #


def _records(result: Any) -> list:
    """Records out of a neo4j ``EagerResult``, a ``(records, ...)`` tuple or a list."""
    if result is None:
        return []
    if isinstance(result, tuple):
        return list(result[0] or [])
    records = getattr(result, "records", None)
    if records is not None:
        return list(records)
    return list(result)


def _value(record: Any, key: str, default: Any = None) -> Any:
    try:
        return record[key]
    except (KeyError, TypeError, IndexError):
        get = getattr(record, "get", None)
        return get(key, default) if callable(get) else default


def _no_repo_filter(must: Optional[list] = None, must_not: Optional[list] = None) -> Filter:
    """Points whose ``repo`` payload is missing or null (see the module note)."""
    return Filter(
        must=must,
        must_not=must_not,
        should=[
            IsNullCondition(is_null=PayloadField(key="repo")),
            IsEmptyCondition(is_empty=PayloadField(key="repo")),
        ],
    )


def _batched(items: list, size: int) -> Iterable[list]:
    size = max(1, int(size or 1))
    for start in range(0, len(items), size):
        yield items[start : start + size]


def _run_write_loop(graph: Any, cypher: str, params: dict, key: str = "n") -> int:
    """``GraphStore.run_write_loop`` when available, else the same loop locally."""
    runner = getattr(graph, "run_write_loop", None)
    if callable(runner):
        return runner(cypher, params, key=key)
    total = 0
    for _ in range(10_000):
        records = _records(graph.query_graph(cypher, params))
        count = int(_value(records[0], key, 0) or 0) if records else 0
        if count <= 0:
            break
        total += count
    else:  # pragma: no cover - runaway query
        logger.warning("write loop did not converge; stopping early")
    return total


# --------------------------------------------------------------------------- #
# Step 1-2: scan + plan
# --------------------------------------------------------------------------- #


def scan_code_points(client: Any, collection: str, batch_size: int) -> tuple[dict[str, int], int]:
    """``{file_path: point_count}`` for every non-wiki point without a ``repo``."""
    per_path: dict[str, int] = {}
    scanned = 0
    offset = None
    scroll_filter = _no_repo_filter(
        must_not=[FieldCondition(key="source", match=MatchValue(value=WIKI_SOURCE))]
    )
    while True:
        points, offset = client.scroll(
            collection_name=collection,
            scroll_filter=scroll_filter,
            limit=batch_size,
            offset=offset,
            with_payload=SCROLL_PAYLOAD,
            with_vectors=False,
        )
        for point in points:
            payload = point.payload or {}
            if payload.get("repo"):
                continue  # already stamped (belt and braces; the filter excludes these)
            file_path = payload.get("file_path")
            if not file_path:
                continue
            per_path[file_path] = per_path.get(file_path, 0) + 1
            scanned += 1
        if offset is None or not points:
            break
    return per_path, scanned


def build_plan(
    per_path: dict[str, int],
    *,
    repos_root: Optional[str] = None,
    repo_map: Optional[dict[str, str]] = None,
    app_map: Optional[dict[str, list[str]]] = None,
) -> list[PlanEntry]:
    """Cluster the scanned paths into repositories and group them into applications."""
    repos = cluster_paths(per_path, repos_root=repos_root, repo_map=repo_map)
    if not repos:
        return []
    groups = group_apps(repos.values(), repos_root=repos_root, app_map=app_map)
    app_of = {name: app for app, names in groups.items() for name in names}

    plan: list[PlanEntry] = []
    for name, repo in repos.items():
        paths = sorted(repo.file_paths)
        plan.append(
            PlanEntry(
                app=app_of.get(name, name),
                repo=name,
                root=repo.root,
                files=len(paths),
                points=sum(per_path.get(p, 0) for p in paths),
                file_paths=paths,
            )
        )
    plan.sort(key=lambda e: (e.app, e.repo))
    return plan


def _repo_for_path(path: str, plan: list[PlanEntry]) -> Optional[PlanEntry]:
    """The plan entry whose root is the longest prefix of ``path``."""
    if not path:
        return None
    normalised = path.replace("\\", "/")
    best: Optional[PlanEntry] = None
    for entry in plan:
        root = entry.root.replace("\\", "/").rstrip("/")
        if not root:
            continue
        if normalised == root or normalised.startswith(root + "/"):
            if best is None or len(root) > len(best.root):
                best = entry
    return best


# --------------------------------------------------------------------------- #
# Step 3-4: Qdrant
# --------------------------------------------------------------------------- #


def ensure_payload_indexes(client: Any, collection: str, warnings: list[str]) -> int:
    """Create the ``app`` / ``repo`` keyword payload indexes; never fatal."""
    created = 0
    for field_name in ("repo", "app"):
        try:
            client.create_payload_index(
                collection_name=collection,
                field_name=field_name,
                field_schema=PayloadSchemaType.KEYWORD,
            )
            created += 1
        except Exception as exc:  # already exists, local mode, older server...
            msg = f"payload index for '{field_name}' not created: {exc}"
            logger.warning(msg)
            warnings.append(msg)
    return created


def stamp_code_points(
    client: Any,
    collection: str,
    plan: list[PlanEntry],
    batch_size: int,
    warnings: list[str],
) -> dict[str, int]:
    """``set_payload`` ``{app, repo, repo_root}`` for every planned file path."""
    summary = {"files": 0, "batches": 0, "repos": 0}
    for entry in plan:
        if not entry.file_paths:
            continue
        summary["repos"] += 1
        for chunk in _batched(entry.file_paths, batch_size):
            try:
                client.set_payload(
                    collection_name=collection,
                    payload={"app": entry.app, "repo": entry.repo, "repo_root": entry.root},
                    points=Filter(
                        must=[FieldCondition(key="file_path", match=MatchAny(any=list(chunk)))]
                    ),
                    wait=True,
                )
            except Exception as exc:
                msg = f"set_payload failed for repo '{entry.repo}' ({len(chunk)} paths): {exc}"
                logger.warning(msg)
                warnings.append(msg)
                continue
            summary["files"] += len(chunk)
            summary["batches"] += 1
    return summary


def scan_wiki_points(client: Any, collection: str, batch_size: int) -> list[tuple[Any, str]]:
    """``[(point_id, symbol_id)]`` for wiki points that have no ``repo`` yet."""
    out: list[tuple[Any, str]] = []
    offset = None
    scroll_filter = _no_repo_filter(
        must=[FieldCondition(key="source", match=MatchValue(value=WIKI_SOURCE))]
    )
    while True:
        points, offset = client.scroll(
            collection_name=collection,
            scroll_filter=scroll_filter,
            limit=batch_size,
            offset=offset,
            with_payload=SCROLL_PAYLOAD,
            with_vectors=False,
        )
        for point in points:
            payload = point.payload or {}
            if payload.get("repo"):
                continue
            out.append((point.id, str(payload.get("symbol_id") or "")))
        if offset is None or not points:
            break
    return out


def resolve_symbol_repos(graph: Any, symbol_ids: list[str], batch_size: int) -> dict[str, dict]:
    """``{symbol_id: {"repo": ..., "path": ...}}`` resolved through Neo4j."""
    resolved: dict[str, dict] = {}
    for chunk in _batched(sorted({sid for sid in symbol_ids if sid}), batch_size):
        try:
            result = graph.query_graph(RESOLVE_WIKI_CYPHER, {"ids": list(chunk)})
        except Exception as exc:
            logger.warning("wiki symbol resolution failed for %d ids: %s", len(chunk), exc)
            continue
        for record in _records(result):
            cid = _value(record, "cid")
            if not cid:
                continue
            resolved[str(cid)] = {
                "repo": _value(record, "repo"),
                "path": _value(record, "path"),
            }
    return resolved


def stamp_wiki_points(
    client: Any,
    collection: str,
    plan: list[PlanEntry],
    wiki_points: list[tuple[Any, str]],
    resolved: dict[str, dict],
    wiki_repo: Optional[str],
    batch_size: int,
    warnings: list[str],
) -> dict[str, int]:
    """Stamp ``{repo, app}`` on wiki points, grouped by the repo they resolved to."""
    app_of = {entry.repo: entry.app for entry in plan}
    by_repo: dict[str, list[Any]] = {}
    unresolved = 0

    for point_id, symbol_id in wiki_points:
        info = resolved.get(symbol_id) or {}
        repo = info.get("repo")
        if not repo:
            entry = _repo_for_path(str(info.get("path") or ""), plan)
            repo = entry.repo if entry else None
        if not repo:
            repo = wiki_repo
        if not repo:
            unresolved += 1
            continue
        by_repo.setdefault(str(repo), []).append(point_id)

    summary = {"stamped": 0, "unresolved": unresolved, "repos": len(by_repo)}
    if unresolved:
        msg = (
            f"{unresolved} wiki point(s) could not be attributed to a repository "
            f"(pass --wiki-repo NAME to assign them explicitly)"
        )
        logger.warning(msg)
        warnings.append(msg)

    for repo, ids in sorted(by_repo.items()):
        payload = {"repo": repo, "app": app_of.get(repo, repo)}
        for chunk in _batched(ids, batch_size):
            try:
                client.set_payload(
                    collection_name=collection,
                    payload=payload,
                    points=list(chunk),
                    wait=True,
                )
            except Exception as exc:
                msg = f"set_payload failed for {len(chunk)} wiki point(s) of '{repo}': {exc}"
                logger.warning(msg)
                warnings.append(msg)
                continue
            summary["stamped"] += len(chunk)
    return summary


# --------------------------------------------------------------------------- #
# Step 5-8: Neo4j
# --------------------------------------------------------------------------- #


def backfill_graph(graph: Any, plan: list[PlanEntry], warnings: list[str]) -> dict[str, int]:
    """Steps 5-8: File identity, Application/Repository nodes, Chunk.repo, WikiPage.repo."""
    summary = {
        "files": 0,
        "applications": 0,
        "repositories": 0,
        "repo_file_edges": 0,
        "chunks": 0,
        "wiki_pages": 0,
    }
    now = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    seen_apps: set[str] = set()

    for entry in plan:
        identity = entry.identity
        root_prefix = entry.root.rstrip("/") + "/"

        # (5) File.app / .repo / .rel_path
        try:
            summary["files"] += _run_write_loop(
                graph,
                FILE_IDENTITY_CYPHER,
                {
                    "root_prefix": root_prefix,
                    "app": entry.app,
                    "repo": entry.repo,
                    "limit": GRAPH_WRITE_LIMIT,
                },
            )
        except Exception as exc:
            msg = f"File backfill failed for '{entry.repo}': {exc}"
            logger.warning(msg)
            warnings.append(msg)
            continue

        # (6) Application + Repository nodes and their CONTAINS edges
        try:
            graph.query_graph(
                IDENTITY_NODES_CYPHER,
                {
                    "aid": identity.app_id,
                    "rid": identity.id,
                    "app": entry.app,
                    "repo": entry.repo,
                    "root": entry.root,
                    "now": now,
                },
            )
            summary["repositories"] += 1
            if entry.app not in seen_apps:
                seen_apps.add(entry.app)
                summary["applications"] += 1
            summary["repo_file_edges"] += _run_write_loop(
                graph,
                REPO_CONTAINS_CYPHER,
                {"repo": entry.repo, "rid": identity.id, "limit": GRAPH_WRITE_LIMIT},
            )
        except Exception as exc:
            msg = f"Repository node backfill failed for '{entry.repo}': {exc}"
            logger.warning(msg)
            warnings.append(msg)

        # (7) Chunk.repo through the owning File
        try:
            summary["chunks"] += _run_write_loop(
                graph,
                CHUNK_REPO_CYPHER,
                {"repo": entry.repo, "limit": GRAPH_WRITE_LIMIT},
            )
        except Exception as exc:
            msg = f"Chunk backfill failed for '{entry.repo}': {exc}"
            logger.warning(msg)
            warnings.append(msg)

    # (8) WikiPage.repo / .app through DOCUMENTS (global, not per repo)
    try:
        summary["wiki_pages"] = _run_write_loop(
            graph, WIKI_PAGE_CYPHER, {"limit": GRAPH_WRITE_LIMIT}
        )
    except Exception as exc:
        msg = f"WikiPage backfill failed: {exc}"
        logger.warning(msg)
        warnings.append(msg)

    return summary


# --------------------------------------------------------------------------- #
# Entry point
# --------------------------------------------------------------------------- #


def run_backfill(options: BackfillOptions) -> dict:
    """Run the backfill and return a summary dict.

    Shape::

        {
          "collection": str, "dry_run": bool,
          "plan": [{"app","repo","root","files","points"}],
          "plan_table": str,
          "qdrant": {"scanned_points", "code_files", "indexes",
                     "code_files_stamped", "code_batches",
                     "wiki_points", "wiki_stamped", "wiki_unresolved"},
          "neo4j": {"files","applications","repositories","repo_file_edges",
                    "chunks","wiki_pages"},
          "warnings": [str],
        }

    ``--no-qdrant`` / ``--no-neo4j`` leave the corresponding sub-dict empty; a
    ``--dry-run`` returns after the plan without writing anything.
    """
    warnings: list[str] = []
    summary: dict[str, Any] = {
        "collection": options.collection,
        "dry_run": bool(options.dry_run),
        "plan": [],
        "plan_table": "",
        "qdrant": {},
        "neo4j": {},
        "warnings": warnings,
    }

    client, owns_client = options.client, False
    graph, owns_graph = options.graph, False
    try:
        # --- Qdrant side ------------------------------------------------- #
        per_path: dict[str, int] = {}
        scanned = 0
        if not options.no_qdrant:
            if client is None:
                from qdrant_client import QdrantClient

                client = QdrantClient(url=options.qdrant_url)
                owns_client = True
            per_path, scanned = scan_code_points(client, options.collection, options.batch_size)

        plan = build_plan(
            per_path,
            repos_root=options.repos_root,
            repo_map=options.repo_map,
            app_map=options.app_map,
        )
        summary["plan"] = [
            {"app": e.app, "repo": e.repo, "root": e.root, "files": e.files, "points": e.points}
            for e in plan
        ]
        summary["plan_table"] = format_plan_table(plan)
        if not options.no_qdrant:
            summary["qdrant"] = {"scanned_points": scanned, "code_files": len(per_path)}
        logger.info("Backfill plan:\n%s", summary["plan_table"])

        if options.dry_run:
            return summary

        if not options.no_qdrant and plan:
            summary["qdrant"]["indexes"] = ensure_payload_indexes(
                client, options.collection, warnings
            )
            stamped = stamp_code_points(
                client, options.collection, plan, options.batch_size, warnings
            )
            summary["qdrant"]["code_files_stamped"] = stamped["files"]
            summary["qdrant"]["code_batches"] = stamped["batches"]

        # --- Neo4j side ---------------------------------------------------- #
        if not options.no_neo4j:
            if graph is None:
                from code_vector_graph.stores.graph_store import GraphStore

                graph = GraphStore(
                    uri=options.neo4j_uri,
                    user=options.neo4j_user,
                    password=options.neo4j_password,
                )
                owns_graph = True

        # (4) wiki points need the graph to map symbol_id -> repo
        if not options.no_qdrant:
            wiki_points = scan_wiki_points(client, options.collection, options.batch_size)
            summary["qdrant"]["wiki_points"] = len(wiki_points)
            if wiki_points:
                resolved: dict[str, dict] = {}
                if not options.no_neo4j and graph is not None:
                    resolved = resolve_symbol_repos(
                        graph, [sid for _, sid in wiki_points], options.batch_size
                    )
                elif not options.wiki_repo:
                    warnings.append(
                        "wiki points cannot be resolved without Neo4j; "
                        "pass --wiki-repo NAME or drop --no-neo4j"
                    )
                wiki_summary = stamp_wiki_points(
                    client,
                    options.collection,
                    plan,
                    wiki_points,
                    resolved,
                    options.wiki_repo,
                    options.batch_size,
                    warnings,
                )
                summary["qdrant"]["wiki_stamped"] = wiki_summary["stamped"]
                summary["qdrant"]["wiki_unresolved"] = wiki_summary["unresolved"]

        if not options.no_neo4j and graph is not None and plan:
            summary["neo4j"] = backfill_graph(graph, plan, warnings)

        return summary
    finally:
        if owns_graph and graph is not None:
            try:
                graph.close()
            except Exception:  # pragma: no cover - best effort
                logger.debug("closing the graph store failed", exc_info=True)
        if owns_client and client is not None:
            try:
                client.close()
            except Exception:  # pragma: no cover - best effort
                logger.debug("closing the Qdrant client failed", exc_info=True)
