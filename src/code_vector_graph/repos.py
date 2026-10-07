"""Application / repository identity and legacy path clustering.

This module is intentionally **stdlib-only** (no stores, embeddings, Qdrant or
Neo4j imports) so that the ingestion pipeline, the MCP server, the FastAPI
layer and any backfill CLI can all depend on it without pulling heavy deps.

Identity model::

    Application  onebid                      id = uuid5(NAMESPACE, "app:onebid")
     └─ Repository backend_nodejs_global_tnlm  id = uuid5(NAMESPACE, "repo:backend_nodejs_global_tnlm")
        root = /Users/.../onebid/backend/backend_nodejs_global_tnlm

Two entry points cover the two data situations:

* Newly indexed data: :func:`resolve_repo_identity` computes the identity for a
  ``repo_path`` (with optional ``--repo-name`` / ``--app-name`` overrides and the
  ``CVG_REPOS_ROOT`` convention).
* Legacy data (payloads without ``repo``): :func:`cluster_paths` derives repo
  roots from the set of indexed file paths, and :func:`group_apps` groups those
  repos into applications.

All path comparisons here are string based (posix separators, tolerant of
backslashes) and never touch the filesystem, so they work on paths recorded on
another machine or on relative legacy paths.
"""

from __future__ import annotations

import json
import logging
import posixpath
import uuid
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol, runtime_checkable

logger = logging.getLogger(__name__)

__all__ = [
    "NAMESPACE",
    "PROJECT_MARKER_DIRS",
    "DerivedRepo",
    "RepoIdentity",
    "app_from_repos_root",
    "cluster_paths",
    "display_rel_path",
    "group_apps",
    "parse_json_map",
    "resolve_repo_identity",
]

NAMESPACE = uuid.NAMESPACE_URL

# Directory names that mark "this directory is a project root". A directory
# containing one of these as a direct child is treated as a repo root even if it
# has no files of its own (typical for a monorepo: ``mono/packages/a/src/...``).
PROJECT_MARKER_DIRS = frozenset(
    {
        "src",
        "lib",
        "app",
        "apps",
        "packages",
        "test",
        "tests",
        "__tests__",
        "spec",
        "components",
        "pages",
        "public",
        "scripts",
        "bin",
        "config",
        "server",
        "client",
        "api",
    }
)


# --------------------------------------------------------------------------- #
# Path helpers (pure string manipulation)
# --------------------------------------------------------------------------- #


def _norm(path: str | None) -> str:
    """Normalise a path string for comparison: posix separators, no trailing slash.

    Does not resolve symlinks or consult the filesystem.
    """
    if not path:
        return ""
    p = path.replace("\\", "/")
    p = posixpath.normpath(p)
    if len(p) > 1:
        p = p.rstrip("/")
    return p


def _is_under(path: str, root: str) -> bool:
    """True when normalised ``path`` is strictly inside normalised ``root``."""
    if not root:
        return False
    if root == "/":
        return path.startswith("/") and path != "/"
    return path.startswith(root + "/")


def _relative_to(path: str, root: str) -> str | None:
    """``path`` relative to ``root`` (both normalised), or None when not under it."""
    if path == root:
        return ""
    if not _is_under(path, root):
        return None
    if root == "/":
        return path[1:]
    return path[len(root) + 1 :]


def _basename(path: str) -> str:
    base = posixpath.basename(path)
    return base if base else path


# --------------------------------------------------------------------------- #
# Identity
# --------------------------------------------------------------------------- #


def app_from_repos_root(root: str, repos_root: str | None) -> str | None:
    """First path component of ``root`` below ``repos_root``.

    ``/Users/x/Repository`` + ``/Users/x/Repository/onebid/backend/foo`` -> ``"onebid"``.
    Returns None when ``repos_root`` is unset, ``root`` is not under it, or
    ``root == repos_root``.
    """
    if not repos_root or not root:
        return None
    rel = _relative_to(_norm(root), _norm(repos_root))
    if not rel:
        return None
    first = rel.split("/", 1)[0]
    return first or None


@dataclass(frozen=True)
class RepoIdentity:
    """Identity of one indexed repository inside an application."""

    app: str
    name: str
    root: str

    @property
    def id(self) -> str:
        """Stable Repository node id: ``uuid5(NAMESPACE, "repo:<name>")``."""
        return str(uuid.uuid5(NAMESPACE, f"repo:{self.name}"))

    @property
    def app_id(self) -> str:
        """Stable Application node id: ``uuid5(NAMESPACE, "app:<app>")``."""
        return str(uuid.uuid5(NAMESPACE, f"app:{self.app}"))

    def rel_path(self, file_path: str) -> str:
        """``file_path`` relative to :attr:`root` when it lives under the root.

        Comparison is purely string based (normalised separators); paths that are
        not under the root are returned unchanged.
        """
        rel = _relative_to(_norm(file_path), _norm(self.root))
        return file_path if rel is None else rel


def resolve_repo_identity(
    repo_path: str,
    repo_name: str | None = None,
    app_name: str | None = None,
    repos_root: str | None = None,
) -> RepoIdentity:
    """Compute the identity for a repository being indexed.

    * ``root`` = ``Path(repo_path).resolve()``
    * ``name`` = ``repo_name`` or the basename of the resolved root
    * ``app``  = ``app_name`` or the first component after ``repos_root`` or ``name``
    """
    root = str(Path(repo_path).resolve())
    name = repo_name or Path(root).name or root
    app = app_name or app_from_repos_root(root, repos_root) or name
    return RepoIdentity(app=app, name=name, root=root)


def parse_json_map(raw: str | None) -> dict:
    """Parse a JSON object from an env var (``CVG_REPO_MAP`` / ``CVG_APP_MAP``).

    Returns ``{}`` for empty input or when the value is not a JSON object; a
    warning is logged for invalid input so misconfiguration is visible.
    """
    if raw is None or not raw.strip():
        return {}
    try:
        value = json.loads(raw)
    except (TypeError, ValueError) as exc:
        logger.warning("Ignoring invalid JSON map %r: %s", raw, exc)
        return {}
    if not isinstance(value, dict):
        logger.warning("Ignoring JSON map %r: expected an object, got %s", raw, type(value).__name__)
        return {}
    return value


# --------------------------------------------------------------------------- #
# Legacy derivation: cluster file paths into repositories
# --------------------------------------------------------------------------- #


@dataclass
class DerivedRepo:
    """A repository derived from a set of indexed file paths."""

    name: str
    root: str
    file_paths: set[str] = field(default_factory=set)

    @property
    def count(self) -> int:
        return len(self.file_paths)


@runtime_checkable
class _RepoLike(Protocol):
    name: str
    root: str


class _DirNode:
    __slots__ = ("path", "dirs", "files")

    def __init__(self, path: str) -> None:
        self.path = path
        self.dirs: dict[str, _DirNode] = {}
        self.files: set[str] = set()  # original (un-normalised) file paths

    def child(self, name: str) -> _DirNode:
        node = self.dirs.get(name)
        if node is None:
            if self.path is None:  # virtual root
                child_path = "/" if name == "" else name
            else:
                child_path = posixpath.join(self.path, name)
            node = _DirNode(child_path)
            self.dirs[name] = node
        return node

    def is_project_root(self) -> bool:
        return bool(self.files) or any(name in PROJECT_MARKER_DIRS for name in self.dirs)

    def all_files(self) -> set[str]:
        out = set(self.files)
        for node in self.dirs.values():
            out |= node.all_files()
        return out


def _build_trie(paths: Iterable[tuple[str, str]]) -> _DirNode:
    """Build a directory trie from ``(original_path, normalised_path)`` pairs."""
    root = _DirNode(None)  # type: ignore[arg-type]
    for original, norm in paths:
        parts = norm.split("/")
        node = root
        for name in parts[:-1]:
            node = node.child(name)
        node.files.add(original)
    return root


def _collect_roots(
    node: _DirNode,
    repos_root: str,
    out: list[tuple[str, set[str]]],
) -> None:
    """Walk top-down; emit ``(root_path, files)`` for every repo root found."""
    # Nodes at or above repos_root can never be repo roots.
    blocked = bool(repos_root) and (
        node.path == repos_root or _is_under(repos_root, node.path)
    )
    if not blocked and node.is_project_root():
        out.append((node.path, node.all_files()))
        return
    if node.files:
        # Fallback: files that live directly in a blocked directory (e.g. a
        # loose file straight under repos_root) get their parent dir as root.
        out.append((node.path, set(node.files)))
    for name in sorted(node.dirs):
        _collect_roots(node.dirs[name], repos_root, out)


def _disambiguate(roots: list[str], reserved: set[str]) -> dict[str, str]:
    """Map each root to a unique display name.

    Names start as ``basename(root)``; on collision (between derived roots or
    with a ``reserved`` explicit name) the colliding entries grow one parent
    component at a time (``parent/basename``) until unique.
    """
    parts = {r: [p for p in r.split("/") if p] or [r] for r in roots}
    depth = {r: 1 for r in roots}

    def name_of(r: str) -> str:
        comps = parts[r]
        return "/".join(comps[-depth[r] :])

    while True:
        names: dict[str, list[str]] = {}
        for r in roots:
            names.setdefault(name_of(r), []).append(r)
        colliding = [
            r
            for n, rs in names.items()
            for r in rs
            if len(rs) > 1 or n in reserved
        ]
        growable = [r for r in colliding if depth[r] < len(parts[r])]
        if not growable:
            break
        for r in growable:
            depth[r] += 1

    result: dict[str, str] = {}
    for r in roots:
        n = name_of(r)
        if n in reserved or n in result.values():
            n = r  # last resort: the full root is always unique
        result[r] = n
    return result


def cluster_paths(
    paths: Iterable[str],
    *,
    repos_root: str | None = None,
    repo_map: dict[str, str] | None = None,
) -> dict[str, DerivedRepo]:
    """Derive repositories from a set of indexed file paths.

    Algorithm (pure and deterministic):

    1. Skip empty paths and paths without a directory component.
    2. ``repo_map`` (``{repo_name: root}``) is an explicit override: a path under
       a mapped root belongs to that repo (longest root wins).
    3. Remaining paths are placed in a directory trie. Walking top-down, a
       directory is a repo root when it is the first directory on its branch
       (strictly below ``repos_root`` when given) that has a direct file child
       or a child directory named in :data:`PROJECT_MARKER_DIRS`.
    4. Names are ``basename(root)``; colliding basenames are disambiguated as
       ``parent/basename``.

    Returns ``{name: DerivedRepo}`` sorted by name.
    """
    norm_repos_root = _norm(repos_root)

    mapped: list[tuple[str, str, str]] = []  # (name, norm_root, original_root)
    for name, root in (repo_map or {}).items():
        if not name or not isinstance(root, str) or not root.strip():
            continue
        mapped.append((str(name), _norm(root), root))
    # longest root first so nested overrides win
    mapped.sort(key=lambda m: len(m[1]), reverse=True)

    mapped_files: dict[str, set[str]] = {}
    remaining: list[tuple[str, str]] = []
    for original in paths:
        if not original or not isinstance(original, str):
            continue
        norm = _norm(original)
        if not norm or "/" not in norm:
            continue  # no directory component
        for name, mroot, _ in mapped:
            if _is_under(norm, mroot):
                mapped_files.setdefault(name, set()).add(original)
                break
        else:
            remaining.append((original, norm))

    result: dict[str, DerivedRepo] = {}
    for name, mroot, _original_root in mapped:
        files = mapped_files.get(name)
        if files:
            result[name] = DerivedRepo(name=name, root=mroot, file_paths=files)

    trie = _build_trie(remaining)
    found: list[tuple[str, set[str]]] = []
    for top in sorted(trie.dirs):
        _collect_roots(trie.dirs[top], norm_repos_root, found)

    # Merge duplicates defensively (a root can only be emitted once, but keep
    # the function robust to future changes) and name them.
    by_root: dict[str, set[str]] = {}
    for root, files in found:
        by_root.setdefault(root, set()).update(files)
    names = _disambiguate(sorted(by_root), reserved=set(result))
    for root in sorted(by_root):
        name = names[root]
        result[name] = DerivedRepo(name=name, root=root, file_paths=by_root[root])

    return dict(sorted(result.items()))


def group_apps(
    repos: Iterable[_RepoLike],
    *,
    repos_root: str | None = None,
    app_map: dict[str, list[str]] | None = None,
) -> dict[str, list[str]]:
    """Group repositories into applications: ``{app: [repo names sorted]}``.

    Resolution order per repo: the ``app_map`` entry (``{app: [names]}`` or
    ``{app: [roots]}``) that lists the repo, then the first path component below
    ``repos_root``, then the repo name itself.
    """
    by_name: dict[str, str] = {}
    by_root: dict[str, str] = {}
    for app, entries in (app_map or {}).items():
        if not app:
            continue
        if isinstance(entries, str):
            entries = [entries]
        for entry in entries or []:
            if not isinstance(entry, str) or not entry:
                continue
            by_name.setdefault(entry, str(app))
            by_root.setdefault(_norm(entry), str(app))

    groups: dict[str, set[str]] = {}
    for repo in repos:
        name = repo.name
        root = repo.root
        app = by_name.get(name) or by_root.get(_norm(root))
        if not app:
            app = app_from_repos_root(root, repos_root) or name
        groups.setdefault(app, set()).add(name)

    return {app: sorted(names) for app, names in sorted(groups.items())}


def display_rel_path(file_path: str, repo_root: str | None, rel_path: str | None = None) -> str:
    """Path to show in UIs: ``rel_path`` when recorded, else stripped of ``repo_root``."""
    if rel_path:
        return rel_path
    if repo_root:
        rel = _relative_to(_norm(file_path), _norm(repo_root))
        if rel:
            return rel
    return file_path
