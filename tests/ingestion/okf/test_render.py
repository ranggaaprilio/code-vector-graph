"""Tests for the OKF skeleton + renderer (no network)."""

from pathlib import Path

import yaml

from code_vector_graph.ingestion.okf.skeleton import (
    _build_concept_paths,
    build_skeleton,
    concept_name,
    dir_for_label,
    slugify,
)
from code_vector_graph.ingestion.okf.render import write_bundle
from code_vector_graph.ingestion.okf.enricher import fallback_enrichment


def _write_repo(root: Path) -> None:
    (root / "a.js").write_text(
        "export function greet(name) { return format(name); }\n"
        "function format(x) { return 'hi ' + x; }\n"
    )
    (root / "b.js").write_text(
        "export class Greeter {\n"
        "  constructor() {}\n"
        "  greet() { return 1; }\n"
        "}\n"
    )
    (root / "c.js").write_text("function greet() { return 2; }\n")


# --- pure helpers ---------------------------------------------------------

def test_slugify():
    assert slugify("getUserById") == "getuserbyid"
    assert slugify("src/App.tsx") == "src-app-tsx"
    assert slugify("!!!") == ""
    assert len(slugify("x" * 200)) <= 60


def test_dir_for_label():
    assert dir_for_label("Function") == "function"
    assert dir_for_label("TypeAlias") == "typealias"
    assert dir_for_label("Weird") == "weird"


def test_concept_paths_unique_and_deterministic():
    nodes = [
        {"id": "id-aaaa1111", "label": "Function", "properties": {"name": "greet"}},
        {"id": "id-bbbb2222", "label": "Function", "properties": {"name": "greet"}},
        {"id": "id-cccc3333", "label": "Class", "properties": {"name": "Greeter"}},
    ]
    p1 = _build_concept_paths(nodes)
    p2 = _build_concept_paths(list(reversed(nodes)))
    # same mapping regardless of input order (deterministic)
    assert p1 == p2
    # all unique
    assert len(set(p1.values())) == 3
    # two same-named functions get distinct paths under function/
    fn_paths = [v for k, v in p1.items() if v.startswith("function/")]
    assert len(fn_paths) == 2 and fn_paths[0] != fn_paths[1]


# --- skeleton over a real tiny repo --------------------------------------

def test_build_skeleton(tmp_path):
    _write_repo(tmp_path)
    sk = build_skeleton(str(tmp_path))
    labels = {sk.nodes[i]["label"] for i in sk.concept_ids}
    assert "File" in labels and "Function" in labels and "Class" in labels
    # greet(function) calls format -> resolvable by name
    assert sk.resolve_name("format") is not None
    # class Greeter CONTAINS its methods
    greeter = next(i for i in sk.concept_ids if concept_name(sk.nodes[i]) == "Greeter")
    assert sk.contains.get(greeter)


# --- rendering ------------------------------------------------------------

def test_write_bundle_valid_okf(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    _write_repo(repo)
    out = tmp_path / "wiki"

    sk = build_skeleton(str(repo))
    enrichments = {i: fallback_enrichment(sk.nodes[i]) for i in sk.concept_ids}
    overview = {"summary": "Test repo.", "overview": "", "how_it_works": "", "parameters": [], "tags": [], "related": []}

    result = write_bundle(str(out), sk, enrichments, overview, repo_root=str(repo))
    assert result["pages"] == len(sk.concept_ids)

    # root index carries okf_version
    root = (out / "index.md").read_text()
    assert 'okf_version' in root
    root_fm = yaml.safe_load(root.split("---", 2)[1])
    assert root_fm["okf_version"] == "0.1"

    # every concept page: valid frontmatter with a `type`; intra-bundle links resolve
    pages = [p for p in out.rglob("*.md") if p.name != "index.md" and p.name != "log.md"]
    assert pages
    import re
    for page in pages:
        txt = page.read_text()
        assert txt.startswith("---")
        fm = yaml.safe_load(txt.split("---", 2)[1])
        assert fm.get("type")
        for target in re.findall(r"]\((/[^)]+\.md)\)", txt):
            assert (out / target.lstrip("/")).exists(), f"broken link {target} in {page}"

    # relationship links present (Greeter -> its methods)
    greeter_page = next(p for p in pages if p.parent.name == "class")
    assert "## Contains" in greeter_page.read_text()


def test_resource_uses_base_url(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    _write_repo(repo)
    out = tmp_path / "wiki"
    sk = build_skeleton(str(repo))
    enrichments = {i: fallback_enrichment(sk.nodes[i]) for i in sk.concept_ids}
    write_bundle(
        str(out), sk, enrichments, {"summary": ""},
        repo_root=str(repo), repo_base_url="https://github.com/o/r/blob/main",
    )
    a_page = next(p for p in out.rglob("*.md") if p.parent.name == "file" and "a-" in p.name)
    fm = yaml.safe_load(a_page.read_text().split("---", 2)[1])
    assert fm["resource"].startswith("https://github.com/o/r/blob/main/a.js")
