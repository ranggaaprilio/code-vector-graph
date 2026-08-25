"""Application / repository registry and query scoping for the dashboard.

Identity model (see ``code_vector_graph.repos``)::

    Application  onebid
     └─ Repository backend_nodejs_global_tnlm       root=/Users/.../backend_nodejs_global_tnlm
     └─ Repository backend_nodejs_data_sync_onebid  root=/Users/.../backend_nodejs_data_sync_onebid

Two kinds of repositories coexist:

* ``recorded`` — the ingest pipeline / backfill wrote ``Application`` and
  ``Repository`` nodes plus ``File.repo`` / payload ``repo``. Scoping can use
  exact ``repo`` matches (fast, index friendly).
* ``derived`` — legacy data with no identity recorded. The registry clusters the
  indexed file paths into repo roots (:func:`cluster_paths`) and groups them
  into apps (:func:`group_apps`); scoping falls back to ``file_path`` prefixes.

:class:`AppScope` turns an app (optionally narrowed to one repo) into the Qdrant
filter / Cypher predicate / Python predicate the routers need. Everything in
here degrades gracefully: a failing store is logged and the rest still answers.
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Literal

from pydantic import BaseModel, Field
from qdrant_client.models import FieldCondition, Filter, MatchAny, MatchValue

from code_vector_graph.api.serialize import record_get, records_of, scalar
from code_vector_graph.repos import cluster_paths, display_rel_path, group_apps

logger = logging.getLogger(__name__)

WIKI_SOURCE = "okf_wiki"

# Labels whose nodes hang off a File via CONTAINS/DEFINES (used for scoped graph browsing).
FILE_CHILD_LABELS = frozenset(
    {"Chunk", "Class", "Function", "Method", "Field", "Variable", "Import", "Interface", "TypeAlias"}
)


# --------------------------------------------------------------------------- #
# Models
# --------------------------------------------------------------------------- #


class RepoInfo(BaseModel):
    name: str
    root: str
    app: str
    source: Literal["recorded", "derived"] = "derived"
    file_count: int = 0
    chunk_count: int = 0
    languages: dict[str, int] = Field(default_factory=dict)
    has_wiki: bool = False
    wiki_pages: int = 0
    indexed_at: str | None = None

    @property
    def norm_root(self) -> str:
        return _norm_root(self.root)

    @property
    def root_prefix(self) -> str:
        """Root with a trailing slash — the prefix every file path under it starts with."""
        return self.norm_root + "/"

    def contains_path(self, file_path: str | None) -> bool:
        if not file_path or not self.norm_root:
            return False
        return _norm_path(file_path).startswith(self.root_prefix)

    def rel_path(self, file_path: str, rel_path: str | None = None) -> str:
        return display_rel_path(file_path, self.norm_root, rel_path)


class AppInfo(BaseModel):
    name: str
    repos: list[RepoInfo] = Field(default_factory=list)
    file_count: int = 0
    chunk_count: int = 0
    languages: dict[str, int] = Field(default_factory=dict)
    has_wiki: bool = False
    wiki_pages: int = 0
    source: Literal["recorded", "derived"] = "derived"

    @classmethod
    def aggregate(cls, name: str, repos: list[RepoInfo]) -> "AppInfo":
        langs: dict[str, int] = {}
        for r in repos:
            for lang, n in r.languages.items():
                langs[lang] = langs.get(lang, 0) + int(n or 0)
        return cls(
            name=name,
            repos=sorted(repos, key=lambda r: r.name),
            file_count=sum(r.file_count for r in repos),
            chunk_count=sum(r.chunk_count for r in repos),
            languages=dict(sorted(langs.items(), key=lambda kv: (-kv[1], kv[0]))),
            has_wiki=any(r.has_wiki for r in repos),
            wiki_pages=sum(r.wiki_pages for r in repos),
            source="recorded" if repos and all(r.source == "recorded" for r in repos) else "derived",
        )


class FileEntry(BaseModel):
    id: str | None = None
    path: str
    rel_path: str
    repo: str
    language: str | None = None
    line_count: int | None = None
    chunk_count: int = 0


# --------------------------------------------------------------------------- #
# Scope
# --------------------------------------------------------------------------- #


def _norm_path(p: str | None) -> str:
    return (p or "").replace("\\", "/")


def _norm_root(root: str | None) -> str:
    r = _norm_path(root)
    while len(r) > 1 and r.endswith("/"):
        r = r[:-1]
    return r


@dataclass
class AppScope:
    """An application, optionally narrowed to one of its repositories."""

    app: str
    repos: list[RepoInfo] = field(default_factory=list)

    # -- basics -------------------------------------------------------------
    @property
    def repo_names(self) -> list[str]:
        return [r.name for r in self.repos]

    @property
    def repo_roots(self) -> list[str]:
        return [r.norm_root for r in self.repos]

    @property
    def root_prefixes(self) -> list[str]:
        return [r.root_prefix for r in self.repos if r.norm_root]

    @property
    def all_recorded(self) -> bool:
        return bool(self.repos) and all(r.source == "recorded" for r in self.repos)

    @property
    def single_repo(self) -> RepoInfo | None:
        return self.repos[0] if len(self.repos) == 1 else None

    @property
    def label(self) -> str:
        if len(self.repos) == 1:
            return f"{self.app} · {self.repos[0].name}"
        return f"{self.app} · all repos"

    def for_repo(self, name: str) -> "AppScope":
        for r in self.repos:
            if r.name == name:
                return AppScope(app=self.app, repos=[r])
        raise KeyError(f"Unknown repository '{name}' in application '{self.app}'")

    def repo_for(self, file_path: str | None, payload_repo: str | None = None) -> RepoInfo | None:
        """Which repo a file belongs to (payload ``repo`` wins, else longest matching root)."""
        if payload_repo:
            for r in self.repos:
                if r.name == payload_repo:
                    return r
            return None
        best: RepoInfo | None = None
        for r in self.repos:
            if r.contains_path(file_path) and (best is None or len(r.norm_root) > len(best.norm_root)):
                best = r
        return best

    def matches_path(self, file_path: str | None, payload_repo: str | None = None) -> bool:
        if payload_repo:
            return payload_repo in self.repo_names
        return self.repo_for(file_path) is not None

    # -- store predicates ---------------------------------------------------
    def qdrant_filter(self, extra_must: list | None = None) -> Filter | None:
        """Exact ``repo`` filter for recorded scopes; None for derived (post-filter needed)."""
        must = list(extra_must or [])
        if self.all_recorded:
            must.append(FieldCondition(key="repo", match=MatchAny(any=self.repo_names)))
        return Filter(must=must) if must else None

    def cypher_file_where(self, alias: str = "f") -> tuple[str, dict[str, Any]]:
        clause = f"({alias}.repo IN $repos OR any(p IN $roots WHERE {alias}.path STARTS WITH p))"
        return clause, {"repos": self.repo_names, "roots": self.root_prefixes}

    def cypher_wiki_where(self, alias: str = "w") -> tuple[str, dict[str, Any]]:
        """WikiPage in scope: recorded ``repo`` or DOCUMENTS a node under a scoped File."""
        fwhere, params = self.cypher_file_where("f")
        dwhere, _ = self.cypher_file_where("d")
        clause = (
            f"({alias}.repo IN $repos OR EXISTS {{ "
            f"MATCH ({alias})-[:DOCUMENTS]->(d) "
            f"WHERE (d:File AND {dwhere}) "
            f"OR EXISTS {{ MATCH (d)<-[:CONTAINS|DEFINES]-(f:File) WHERE {fwhere} }} }})"
        )
        return clause, params

    def cypher_label_where(self, label: str, alias: str = "n") -> tuple[str, dict[str, Any]]:
        """Predicate restricting nodes of ``label`` to this scope."""
        fwhere, params = self.cypher_file_where("f")
        params = dict(params)
        if label == "File":
            return self.cypher_file_where(alias)
        if label == "WikiPage":
            return self.cypher_wiki_where(alias)
        if label == "Repository":
            return f"{alias}.name IN $repos", params
        if label == "Application":
            params["app"] = self.app
            return f"{alias}.name = $app", params
        if label == "GlossaryEntry":
            return (
                f"({alias}.repo IN $repos OR any(p IN $roots WHERE {alias}.file_path STARTS WITH p))",
                params,
            )
        if label == "Module":
            return (
                f"({alias}.repo IN $repos OR any(p IN $roots WHERE {alias}.path STARTS WITH p))",
                params,
            )
        # Chunk + symbols: reachable from a scoped File.
        return (
            f"({alias}.repo IN $repos OR EXISTS {{ MATCH (f:File)-[:CONTAINS|DEFINES]->({alias}) WHERE {fwhere} }})",
            params,
        )


# --------------------------------------------------------------------------- #
# Registry
# --------------------------------------------------------------------------- #


class ApplicationRegistry:
    """Discovers applications/repositories from Neo4j (recorded ∪ derived) with a Qdrant fallback."""

    def __init__(
        self,
        graph: Any,
        qdrant: Any,
        collection: str,
        ttl: float = 300,
        repos_root: str | None = None,
        repo_map: dict | None = None,
        app_map: dict | None = None,
    ) -> None:
        self.graph = graph
        self.qdrant = qdrant
        self.collection = collection
        self.ttl = float(ttl or 0)
        self.repos_root = repos_root or None
        self.repo_map = dict(repo_map or {})
        self.app_map = dict(app_map or {})
        self._lock = threading.RLock()
        self._apps: dict[str, AppInfo] | None = None
        self._cached_at: float | None = None
        self._files: dict[tuple[str, str], tuple[float, list[FileEntry]]] = {}
        self._scroll_chunks: dict[str, int] | None = None  # file_path -> points (Qdrant fallback)

    # -- public ---------------------------------------------------------------
    @property
    def cached_at(self) -> str | None:
        if self._cached_at is None:
            return None
        return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(self._cached_at))

    def list(self, refresh: bool = False) -> list[AppInfo]:
        with self._lock:
            if refresh or self._stale():
                self._apps = self._discover()
                self._cached_at = time.time()
                self._files.clear()
            return list((self._apps or {}).values())

    def get(self, app: str) -> AppInfo:
        apps = {a.name: a for a in self.list()}
        if app not in apps:
            raise KeyError(f"Unknown application '{app}'")
        return apps[app]

    def scope(self, app: str, repo: str | None = None) -> AppScope:
        info = self.get(app)
        scope = AppScope(app=info.name, repos=list(info.repos))
        return scope.for_repo(repo) if repo else scope

    def files(self, app: str, repo: str | None = None, refresh: bool = False) -> list[FileEntry]:
        scope = self.scope(app, repo)
        key = (app, repo or "")
        with self._lock:
            hit = self._files.get(key)
            if hit and not refresh and self.ttl > 0 and time.time() - hit[0] < self.ttl:
                return hit[1]
            entries = self._load_files(scope)
            self._files[key] = (time.time(), entries)
            return entries

    # -- discovery ------------------------------------------------------------
    def _stale(self) -> bool:
        if self._apps is None or self._cached_at is None:
            return True
        return self.ttl <= 0 or (time.time() - self._cached_at) >= self.ttl

    def _discover(self) -> dict[str, AppInfo]:
        self._scroll_chunks = None
        repos: dict[str, RepoInfo] = {}
        neo4j_ok = True

        try:
            for r in self._discover_recorded():
                repos[r.name] = r
        except Exception:
            neo4j_ok = False
            logger.warning("Application discovery: Neo4j recorded lookup failed", exc_info=True)

        if neo4j_ok:
            try:
                derived = self._discover_legacy_neo4j()
            except Exception:
                neo4j_ok = False
                derived = []
                logger.warning("Application discovery: Neo4j legacy lookup failed", exc_info=True)
            self._merge_derived(repos, derived)

        if not repos:
            try:
                self._merge_derived(repos, self._discover_qdrant())
            except Exception:
                logger.warning("Application discovery: Qdrant fallback failed", exc_info=True)

        for r in repos.values():
            self._fill_counts(r)

        groups: dict[str, list[RepoInfo]] = {}
        for r in repos.values():
            groups.setdefault(r.app, []).append(r)
        return {name: AppInfo.aggregate(name, rs) for name, rs in sorted(groups.items())}

    def _merge_derived(self, repos: dict[str, RepoInfo], derived: list[RepoInfo]) -> None:
        recorded_roots = {r.norm_root for r in repos.values() if r.source == "recorded"}
        for d in derived:
            if d.norm_root in recorded_roots or d.name in repos:
                continue  # recorded identity wins over a derived twin
            repos[d.name] = d

    def _discover_recorded(self) -> list[RepoInfo]:
        raw = self.graph.query_graph(
            "MATCH (a:Application)-[:CONTAINS]->(r:Repository) "
            "RETURN a.name AS app, r.name AS repo, r.root AS root, r.indexed_at AS indexed_at"
        )
        repos: dict[str, RepoInfo] = {}
        for rec in records_of(raw):
            name = record_get(rec, "repo")
            if not name:
                continue
            indexed_at = record_get(rec, "indexed_at")
            if indexed_at is not None and not isinstance(indexed_at, str):
                indexed_at = getattr(indexed_at, "iso_format", lambda: str(indexed_at))()
            repos[name] = RepoInfo(
                name=name,
                root=_norm_root(record_get(rec, "root") or ""),
                app=record_get(rec, "app") or name,
                source="recorded",
                indexed_at=indexed_at,
            )
        if not repos:
            return []
        try:
            raw = self.graph.query_graph(
                "MATCH (f:File) WHERE f.repo IS NOT NULL "
                "RETURN f.repo AS repo, f.language AS language, count(f) AS n"
            )
            for rec in records_of(raw):
                r = repos.get(record_get(rec, "repo"))
                if r is None:
                    continue
                lang = record_get(rec, "language") or "unknown"
                n = int(record_get(rec, "n") or 0)
                r.languages[lang] = r.languages.get(lang, 0) + n
                r.file_count += n
        except Exception:
            logger.warning("Application discovery: File.repo counts failed", exc_info=True)
        return list(repos.values())

    def _discover_legacy_neo4j(self) -> list[RepoInfo]:
        raw = self.graph.query_graph(
            "MATCH (f:File) WHERE f.repo IS NULL RETURN f.path AS path, f.language AS language"
        )
        langs: dict[str, str] = {}
        for rec in records_of(raw):
            path = record_get(rec, "path")
            if path:
                langs[path] = record_get(rec, "language") or "unknown"
        return self._derive(langs)

    def _discover_qdrant(self) -> list[RepoInfo]:
        langs: dict[str, str] = {}
        tally: dict[str, int] = {}
        wiki_not = Filter(must_not=[FieldCondition(key="source", match=MatchValue(value=WIKI_SOURCE))])

        # facet(repo) is a cheap hint that recorded identities exist; it is optional.
        try:
            facet = self.qdrant.facet(collection_name=self.collection, key="repo", limit=1000)
            hits = getattr(facet, "hits", None) or []
            if hits:
                logger.info("Qdrant facet(repo): %d recorded repos", len(hits))
        except Exception:
            logger.debug("Qdrant facet(repo) unavailable", exc_info=True)

        offset = None
        while True:
            points, offset = self.qdrant.scroll(
                collection_name=self.collection,
                limit=1000,
                offset=offset,
                scroll_filter=wiki_not,
                with_payload=["file_path", "language", "source"],
                with_vectors=False,
            )
            for p in points:
                payload = p.payload or {}
                if payload.get("source") == WIKI_SOURCE:
                    continue
                fp = payload.get("file_path")
                if not fp:
                    continue
                tally[fp] = tally.get(fp, 0) + 1
                langs.setdefault(fp, payload.get("language") or "unknown")
            if offset is None or not points:
                break
        self._scroll_chunks = tally
        return self._derive(langs)

    def _derive(self, langs: dict[str, str]) -> list[RepoInfo]:
        if not langs:
            return []
        clusters = cluster_paths(langs.keys(), repos_root=self.repos_root, repo_map=self.repo_map)
        apps = group_apps(clusters.values(), repos_root=self.repos_root, app_map=self.app_map)
        app_of = {name: app for app, names in apps.items() for name in names}
        out = []
        for name, dr in clusters.items():
            lang_counts: dict[str, int] = {}
            for fp in dr.file_paths:
                lang = langs.get(fp) or "unknown"
                lang_counts[lang] = lang_counts.get(lang, 0) + 1
            out.append(
                RepoInfo(
                    name=name,
                    root=_norm_root(dr.root),
                    app=app_of.get(name, name),
                    source="derived",
                    file_count=dr.count,
                    languages=dict(sorted(lang_counts.items(), key=lambda kv: (-kv[1], kv[0]))),
                )
            )
        return out

    # -- per-repo counts -------------------------------------------------------
    def _fill_counts(self, r: RepoInfo) -> None:
        r.chunk_count = self._chunk_count(r)
        r.wiki_pages = self._wiki_count(r)
        r.has_wiki = r.wiki_pages > 0

    def _chunk_count(self, r: RepoInfo) -> int:
        if r.source == "recorded":
            try:
                res = self.qdrant.count(
                    collection_name=self.collection,
                    count_filter=Filter(must=[FieldCondition(key="repo", match=MatchValue(value=r.name))]),
                    exact=True,
                )
                return int(getattr(res, "count", res) or 0)
            except Exception:
                logger.debug("Qdrant count(repo=%s) failed", r.name, exc_info=True)
        if self._scroll_chunks is not None:
            prefix = r.root_prefix
            return sum(n for fp, n in self._scroll_chunks.items() if _norm_path(fp).startswith(prefix))
        try:
            where, params = AppScope(app=r.app, repos=[r]).cypher_file_where("f")
            raw = self.graph.query_graph(
                f"MATCH (f:File) WHERE {where} MATCH (f)-[:CONTAINS]->(c:Chunk) RETURN count(c) AS n",
                params,
            )
            return int(scalar(raw, "n", 0) or 0)
        except Exception:
            logger.debug("Chunk count for %s failed", r.name, exc_info=True)
            return 0

    def _wiki_count(self, r: RepoInfo) -> int:
        try:
            raw = self.graph.query_graph(
                "MATCH (w:WikiPage) WHERE w.repo = $repo RETURN count(w) AS n", {"repo": r.name}
            )
            n = int(scalar(raw, "n", 0) or 0)
            if n or r.source == "recorded" or not r.norm_root:
                return n
            raw = self.graph.query_graph(
                "MATCH (w:WikiPage)-[:DOCUMENTS]->(n) "
                "MATCH (f:File) WHERE (f = n OR (f)-[:CONTAINS|DEFINES]->(n)) "
                "AND f.path STARTS WITH $root_prefix "
                "RETURN count(DISTINCT w) AS n",
                {"root_prefix": r.root_prefix},
            )
            return int(scalar(raw, "n", 0) or 0)
        except Exception:
            logger.debug("Wiki count for %s failed", r.name, exc_info=True)
            return 0

    # -- files ---------------------------------------------------------------
    def _load_files(self, scope: AppScope) -> list[FileEntry]:
        where, params = scope.cypher_file_where("f")
        try:
            raw = self.graph.query_graph(
                f"MATCH (f:File) WHERE {where} "
                "OPTIONAL MATCH (f)-[:CONTAINS]->(c:Chunk) "
                "RETURN f.id AS id, f.path AS path, f.rel_path AS rel_path, f.repo AS repo, "
                "f.language AS language, f.line_count AS line_count, count(c) AS chunk_count "
                "ORDER BY path",
                params,
            )
        except Exception:
            logger.warning("files(%s) failed", scope.label, exc_info=True)
            return []
        entries: list[FileEntry] = []
        for rec in records_of(raw):
            path = record_get(rec, "path")
            if not path:
                continue
            repo = scope.repo_for(path, record_get(rec, "repo"))
            if repo is None:
                repo = scope.repo_for(path)
            if repo is None:
                continue
            entries.append(
                FileEntry(
                    id=(str(record_get(rec, "id")) if record_get(rec, "id") else None),
                    path=path,
                    rel_path=repo.rel_path(path, record_get(rec, "rel_path")),
                    repo=repo.name,
                    language=record_get(rec, "language"),
                    line_count=record_get(rec, "line_count"),
                    chunk_count=int(record_get(rec, "chunk_count") or 0),
                )
            )
        return entries
