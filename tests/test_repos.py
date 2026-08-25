"""Tests for code_vector_graph.repos (app/repo identity + legacy path clustering)."""

import logging
import sys
import uuid

import pytest

from code_vector_graph.repos import (
    NAMESPACE,
    PROJECT_MARKER_DIRS,
    DerivedRepo,
    RepoIdentity,
    app_from_repos_root,
    cluster_paths,
    display_rel_path,
    group_apps,
    parse_json_map,
    resolve_repo_identity,
)

REPOS_ROOT = "/Users/x/Repository"
ONEBID_A = f"{REPOS_ROOT}/onebid/backend/backend_nodejs_global_tnlm"
ONEBID_B = f"{REPOS_ROOT}/onebid/backend/backend_nodejs_data_sync_onebid"
ONEBID_PATHS = [f"{ONEBID_A}/src/a.ts", f"{ONEBID_B}/src/b.ts"]


# --------------------------------------------------------------------------- #
# Module hygiene
# --------------------------------------------------------------------------- #


def test_module_is_stdlib_only():
    """repos.py must be importable without stores/embeddings/qdrant/neo4j."""
    mod = sys.modules["code_vector_graph.repos"]
    source = open(mod.__file__, encoding="utf-8").read()
    for forbidden in ("stores", "embeddings", "qdrant", "neo4j", "ingestion", "retrieval"):
        assert f"import {forbidden}" not in source
        assert f"from code_vector_graph.{forbidden}" not in source
        assert f"from .{forbidden}" not in source


def test_namespace_and_marker_dirs():
    assert NAMESPACE == uuid.NAMESPACE_URL
    assert {"src", "packages", "tests", "app"} <= PROJECT_MARKER_DIRS


# --------------------------------------------------------------------------- #
# RepoIdentity
# --------------------------------------------------------------------------- #


def test_identity_ids_are_stable_uuid5():
    a = RepoIdentity(app="onebid", name="backend_nodejs_global_tnlm", root=ONEBID_A)
    b = RepoIdentity(app="onebid", name="backend_nodejs_global_tnlm", root="/somewhere/else")
    assert a.id == b.id == str(uuid.uuid5(NAMESPACE, "repo:backend_nodejs_global_tnlm"))
    assert a.app_id == b.app_id == str(uuid.uuid5(NAMESPACE, "app:onebid"))
    assert a.id != a.app_id
    assert a.id != RepoIdentity(app="onebid", name="other", root=ONEBID_A).id


def test_identity_is_frozen_and_hashable():
    ident = RepoIdentity(app="a", name="r", root="/r")
    with pytest.raises(AttributeError):
        ident.name = "x"  # type: ignore[misc]
    assert len({ident, RepoIdentity(app="a", name="r", root="/r")}) == 1


def test_rel_path_under_root():
    ident = RepoIdentity(app="onebid", name="tnlm", root=ONEBID_A)
    assert ident.rel_path(f"{ONEBID_A}/src/a.ts") == "src/a.ts"
    assert ident.rel_path(f"{ONEBID_A}/src/deep/nested/b.ts") == "src/deep/nested/b.ts"


def test_rel_path_outside_root_unchanged():
    ident = RepoIdentity(app="onebid", name="tnlm", root=ONEBID_A)
    outside = f"{ONEBID_B}/src/b.ts"
    assert ident.rel_path(outside) == outside
    # prefix-of-a-sibling is NOT "under" the root
    sibling = f"{ONEBID_A}_v2/src/c.ts"
    assert ident.rel_path(sibling) == sibling


def test_rel_path_tolerates_backslashes_and_trailing_slash():
    ident = RepoIdentity(app="a", name="r", root="C:/proj/r/")
    assert ident.rel_path("C:\\proj\\r\\src\\a.ts") == "src/a.ts"


def test_rel_path_relative_legacy_root():
    ident = RepoIdentity(app="sample-repo", name="sample-repo", root="examples/sample-repo")
    assert ident.rel_path("examples/sample-repo/a.js") == "a.js"


# --------------------------------------------------------------------------- #
# app_from_repos_root / resolve_repo_identity
# --------------------------------------------------------------------------- #


def test_app_from_repos_root():
    assert app_from_repos_root(ONEBID_A, REPOS_ROOT) == "onebid"
    assert app_from_repos_root(f"{REPOS_ROOT}/poc/code-vector-graph", REPOS_ROOT + "/") == "poc"
    assert app_from_repos_root(f"{REPOS_ROOT}/tiny", REPOS_ROOT) == "tiny"


def test_app_from_repos_root_none_cases():
    assert app_from_repos_root(ONEBID_A, None) is None
    assert app_from_repos_root(ONEBID_A, "") is None
    assert app_from_repos_root(REPOS_ROOT, REPOS_ROOT) is None
    assert app_from_repos_root("/other/place/repo", REPOS_ROOT) is None
    # sibling with shared string prefix is not under repos_root
    assert app_from_repos_root(f"{REPOS_ROOT}2/foo", REPOS_ROOT) is None


def test_resolve_repo_identity_defaults(tmp_path):
    repo = tmp_path / "myrepo"
    repo.mkdir()
    ident = resolve_repo_identity(str(repo))
    assert ident.root == str(repo.resolve())
    assert ident.name == "myrepo"
    assert ident.app == "myrepo"  # no repos_root, no override -> app == repo


def test_resolve_repo_identity_resolves_relative_and_dotted_paths(tmp_path, monkeypatch):
    repo = tmp_path / "myrepo"
    repo.mkdir()
    monkeypatch.chdir(tmp_path)
    ident = resolve_repo_identity("./myrepo/../myrepo")
    assert ident.root == str(repo.resolve())
    assert ident.name == "myrepo"


def test_resolve_repo_identity_with_repos_root(tmp_path):
    repo = tmp_path / "onebid" / "backend" / "backend_nodejs_global_tnlm"
    repo.mkdir(parents=True)
    ident = resolve_repo_identity(str(repo), repos_root=str(tmp_path.resolve()))
    assert ident.app == "onebid"
    assert ident.name == "backend_nodejs_global_tnlm"
    assert ident.root == str(repo.resolve())


def test_resolve_repo_identity_repos_root_not_matching_falls_back_to_name(tmp_path):
    repo = tmp_path / "solo"
    repo.mkdir()
    ident = resolve_repo_identity(str(repo), repos_root="/definitely/not/here")
    assert ident.app == "solo"


def test_resolve_repo_identity_overrides_win(tmp_path):
    repo = tmp_path / "onebid" / "backend" / "backend_nodejs_global_tnlm"
    repo.mkdir(parents=True)
    ident = resolve_repo_identity(
        str(repo),
        repo_name="tnlm",
        app_name="OneBid",
        repos_root=str(tmp_path.resolve()),
    )
    assert ident.name == "tnlm"
    assert ident.app == "OneBid"
    assert ident.id == RepoIdentity(app="x", name="tnlm", root="/y").id


# --------------------------------------------------------------------------- #
# parse_json_map
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("raw", [None, "", "   ", "\n"])
def test_parse_json_map_empty(raw):
    assert parse_json_map(raw) == {}


@pytest.mark.parametrize("raw", ["{not json", "[1, 2]", '"string"', "42"])
def test_parse_json_map_invalid_logs_warning(raw, caplog):
    with caplog.at_level(logging.WARNING, logger="code_vector_graph.repos"):
        assert parse_json_map(raw) == {}
    assert any(r.levelno == logging.WARNING for r in caplog.records)


def test_parse_json_map_valid():
    assert parse_json_map('{"tnlm": "/r/tnlm"}') == {"tnlm": "/r/tnlm"}
    assert parse_json_map('{"onebid": ["a", "b"]}') == {"onebid": ["a", "b"]}


# --------------------------------------------------------------------------- #
# cluster_paths
# --------------------------------------------------------------------------- #


def test_cluster_onebid_layout_two_repos():
    repos = cluster_paths(ONEBID_PATHS)
    assert set(repos) == {"backend_nodejs_global_tnlm", "backend_nodejs_data_sync_onebid"}
    assert repos["backend_nodejs_global_tnlm"].root == ONEBID_A
    assert repos["backend_nodejs_global_tnlm"].file_paths == {f"{ONEBID_A}/src/a.ts"}
    assert repos["backend_nodejs_data_sync_onebid"].root == ONEBID_B
    assert repos["backend_nodejs_data_sync_onebid"].file_paths == {f"{ONEBID_B}/src/b.ts"}
    assert repos["backend_nodejs_global_tnlm"].count == 1


def test_cluster_onebid_layout_with_repos_root_same_result():
    repos = cluster_paths(ONEBID_PATHS, repos_root=REPOS_ROOT)
    assert set(repos) == {"backend_nodejs_global_tnlm", "backend_nodejs_data_sync_onebid"}


def test_cluster_poc_layout_multiple_files_per_repo():
    paths = [
        f"{REPOS_ROOT}/poc/code-vector-graph/src/x.py",
        f"{REPOS_ROOT}/poc/code-vector-graph/tests/y.py",
        f"{REPOS_ROOT}/poc/white-board/app/page.tsx",
    ]
    repos = cluster_paths(paths)
    assert set(repos) == {"code-vector-graph", "white-board"}
    assert repos["code-vector-graph"].root == f"{REPOS_ROOT}/poc/code-vector-graph"
    assert repos["code-vector-graph"].file_paths == set(paths[:2])
    assert repos["white-board"].file_paths == {paths[2]}


def test_cluster_monorepo_packages_is_one_repo():
    paths = ["/r/mono/packages/a/src/i.ts", "/r/mono/packages/b/src/j.ts"]
    repos = cluster_paths(paths)
    assert list(repos) == ["mono"]
    assert repos["mono"].root == "/r/mono"
    assert repos["mono"].file_paths == set(paths)


def test_cluster_relative_paths():
    paths = ["examples/sample-repo/a.js", "examples/sample-repo/b.js"]
    repos = cluster_paths(paths)
    assert list(repos) == ["sample-repo"]
    assert repos["sample-repo"].root == "examples/sample-repo"
    assert repos["sample-repo"].file_paths == set(paths)


def test_cluster_files_directly_under_repo_without_markers():
    repos = cluster_paths(["/r/tiny/main.js"])
    assert list(repos) == ["tiny"]
    assert repos["tiny"].root == "/r/tiny"


def test_cluster_files_directly_under_repo_without_markers_and_repos_root():
    repos = cluster_paths(["/r/tiny/main.js", "/r/tiny/util.js"], repos_root="/r")
    assert list(repos) == ["tiny"]
    assert repos["tiny"].root == "/r/tiny"
    assert repos["tiny"].count == 2


def test_cluster_repos_root_is_never_a_repo_root():
    # Without repos_root, "/r" has a marker child ("src") -> "/r" would be the root.
    paths = ["/r/src/a.ts", "/r/other/lib/b.ts"]
    assert list(cluster_paths(paths)) == ["r"]
    # With repos_root="/r" the walk must go below it.
    repos = cluster_paths(paths, repos_root="/r")
    assert set(repos) == {"src", "other"}
    assert repos["other"].root == "/r/other"


def test_cluster_loose_file_under_repos_root_falls_back_to_parent_dir():
    repos = cluster_paths(["/r/loose.js", "/r/tiny/main.js"], repos_root="/r")
    assert set(repos) == {"r", "tiny"}
    assert repos["r"].root == "/r"
    assert repos["r"].file_paths == {"/r/loose.js"}


def test_cluster_skips_empty_and_bare_filenames():
    repos = cluster_paths(["", "README.md", "/r/tiny/main.js", None])  # type: ignore[list-item]
    assert list(repos) == ["tiny"]


def test_cluster_tolerates_backslashes():
    repos = cluster_paths(["C:\\proj\\alpha\\src\\a.ts", "C:\\proj\\beta\\src\\b.ts"])
    assert set(repos) == {"alpha", "beta"}
    assert repos["alpha"].root == "C:/proj/alpha"
    # original path strings are preserved in file_paths
    assert repos["alpha"].file_paths == {"C:\\proj\\alpha\\src\\a.ts"}


def test_cluster_basename_collision_disambiguated_with_parent():
    paths = ["/r/team-a/backend/src/a.ts", "/r/team-b/backend/src/b.ts"]
    repos = cluster_paths(paths)
    assert set(repos) == {"team-a/backend", "team-b/backend"}
    assert repos["team-a/backend"].root == "/r/team-a/backend"
    assert repos["team-b/backend"].root == "/r/team-b/backend"


def test_cluster_repo_map_override_longest_root_wins():
    paths = [
        "/r/mono/packages/a/src/i.ts",
        "/r/mono/packages/b/src/j.ts",
        "/r/other/src/k.ts",
    ]
    repos = cluster_paths(
        paths,
        repo_map={"mono": "/r/mono", "pkg-b": "/r/mono/packages/b/"},
    )
    assert set(repos) == {"mono", "pkg-b", "other"}
    assert repos["pkg-b"].file_paths == {"/r/mono/packages/b/src/j.ts"}
    assert repos["pkg-b"].root == "/r/mono/packages/b"
    assert repos["mono"].file_paths == {"/r/mono/packages/a/src/i.ts"}
    assert repos["other"].file_paths == {"/r/other/src/k.ts"}


def test_cluster_repo_map_without_matching_paths_is_omitted():
    repos = cluster_paths(["/r/tiny/main.js"], repo_map={"ghost": "/nowhere"})
    assert list(repos) == ["tiny"]


def test_cluster_derived_name_colliding_with_repo_map_name_is_disambiguated():
    repos = cluster_paths(
        ["/a/backend/src/x.ts", "/b/backend/src/y.ts"],
        repo_map={"backend": "/a/backend"},
    )
    assert set(repos) == {"backend", "b/backend"}
    assert repos["backend"].root == "/a/backend"


def test_cluster_is_deterministic_regardless_of_input_order():
    paths = ONEBID_PATHS + ["/r/mono/packages/a/src/i.ts", "/r/tiny/main.js"]
    first = cluster_paths(paths)
    second = cluster_paths(list(reversed(paths)))
    assert list(first) == list(second) == sorted(first)
    assert {k: (v.root, v.file_paths) for k, v in first.items()} == {
        k: (v.root, v.file_paths) for k, v in second.items()
    }


def test_cluster_returns_derived_repo_instances():
    repos = cluster_paths(ONEBID_PATHS)
    assert all(isinstance(r, DerivedRepo) for r in repos.values())


# --------------------------------------------------------------------------- #
# group_apps
# --------------------------------------------------------------------------- #


def _onebid_repos():
    return list(cluster_paths(ONEBID_PATHS).values())


def test_group_apps_default_app_equals_repo():
    groups = group_apps(_onebid_repos())
    assert groups == {
        "backend_nodejs_data_sync_onebid": ["backend_nodejs_data_sync_onebid"],
        "backend_nodejs_global_tnlm": ["backend_nodejs_global_tnlm"],
    }


def test_group_apps_with_repos_root_onebid():
    groups = group_apps(_onebid_repos(), repos_root=REPOS_ROOT)
    assert groups == {"onebid": ["backend_nodejs_data_sync_onebid", "backend_nodejs_global_tnlm"]}


def test_group_apps_with_repos_root_mixed():
    repos = _onebid_repos() + [DerivedRepo("solo", "/elsewhere/solo", {"/elsewhere/solo/a.js"})]
    groups = group_apps(repos, repos_root=REPOS_ROOT)
    assert groups == {
        "onebid": ["backend_nodejs_data_sync_onebid", "backend_nodejs_global_tnlm"],
        "solo": ["solo"],
    }


def test_group_apps_app_map_by_name_wins_over_repos_root():
    groups = group_apps(
        _onebid_repos(),
        repos_root=REPOS_ROOT,
        app_map={"OneBidApp": ["backend_nodejs_global_tnlm"]},
    )
    assert groups == {
        "OneBidApp": ["backend_nodejs_global_tnlm"],
        "onebid": ["backend_nodejs_data_sync_onebid"],
    }


def test_group_apps_app_map_by_root():
    groups = group_apps(
        _onebid_repos(),
        app_map={"onebid": [ONEBID_A + "/", ONEBID_B.replace("/", "\\")]},
    )
    assert groups == {"onebid": ["backend_nodejs_data_sync_onebid", "backend_nodejs_global_tnlm"]}


def test_group_apps_accepts_repo_identity_objects():
    repos = [
        RepoIdentity(app="ignored", name="backend_nodejs_global_tnlm", root=ONEBID_A),
        RepoIdentity(app="ignored", name="backend_nodejs_data_sync_onebid", root=ONEBID_B),
    ]
    assert group_apps(repos, repos_root=REPOS_ROOT) == {
        "onebid": ["backend_nodejs_data_sync_onebid", "backend_nodejs_global_tnlm"]
    }


def test_group_apps_empty():
    assert group_apps([]) == {}


# --------------------------------------------------------------------------- #
# display_rel_path
# --------------------------------------------------------------------------- #


def test_display_rel_path_prefers_recorded_rel_path():
    assert display_rel_path(f"{ONEBID_A}/src/a.ts", ONEBID_A, rel_path="custom/a.ts") == "custom/a.ts"


def test_display_rel_path_strips_repo_root():
    assert display_rel_path(f"{ONEBID_A}/src/a.ts", ONEBID_A) == "src/a.ts"
    assert display_rel_path(f"{ONEBID_A}/src/a.ts", ONEBID_A + "/") == "src/a.ts"


def test_display_rel_path_no_root_or_not_under_root():
    fp = f"{ONEBID_A}/src/a.ts"
    assert display_rel_path(fp, None) == fp
    assert display_rel_path(fp, "") == fp
    assert display_rel_path(fp, ONEBID_B) == fp
    assert display_rel_path(fp, ONEBID_A + "_v2") == fp
