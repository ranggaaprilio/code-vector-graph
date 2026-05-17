from pathlib import Path

from src.glossary import (
    build_glossary_graph,
    extract_comment_glossary,
    load_manual_glossary,
)
from src.graph_extractor import extract_graph_entities
from src.parser import parse_file


def _graph_for(path: Path, grammar: str = "typescript"):
    parsed = parse_file(str(path), grammar)
    assert parsed is not None
    graph_data = extract_graph_entities(
        parsed["tree"],
        parsed["source_bytes"],
        str(path),
        "typescript",
        "hash",
    )
    return parsed, graph_data


def test_load_manual_glossary_missing_file_returns_empty(tmp_path):
    entries = load_manual_glossary(str(tmp_path / "missing.yml"), str(tmp_path))

    assert entries == []


def test_load_manual_glossary_skips_invalid_entries(tmp_path):
    glossary = tmp_path / "glossary.yml"
    glossary.write_text(
        """
entries:
  - term: userId
    kind: variable
    file_path: src/session.ts
    summary: User identifier.
  - term: missingSummary
    kind: variable
""",
        encoding="utf-8",
    )

    entries = load_manual_glossary(str(glossary), str(tmp_path))

    assert len(entries) == 1
    assert entries[0]["term"] == "userId"
    assert entries[0]["source"] == "manual"
    assert entries[0]["file_path"] == str(tmp_path / "src/session.ts")


def test_extract_comment_glossary_for_symbols(tmp_path):
    source = tmp_path / "sample.ts"
    source.write_text(
        """
/** User model. */
class User {
  /** Display name. */
  name: string;

  /** Greets the user. */
  greet() { return this.name; }
}

/** Tracks number of users. */
const userCount = 1;
""",
        encoding="utf-8",
    )
    parsed, graph_data = _graph_for(source)

    entries = extract_comment_glossary(
        parsed["tree"],
        parsed["source_bytes"],
        str(source),
        graph_data,
    )
    found = {(entry["kind"], entry["term"]): entry["summary"] for entry in entries}

    assert found[("class", "User")] == "User model."
    assert found[("field", "name")] == "Display name."
    assert found[("method", "greet")] == "Greets the user."
    assert found[("variable", "userCount")] == "Tracks number of users."


def test_build_glossary_graph_manual_overrides_comment(tmp_path):
    source = tmp_path / "sample.ts"
    source.write_text(
        """
/** Comment summary. */
const userId = "1";
""",
        encoding="utf-8",
    )
    parsed, graph_data = _graph_for(source)
    comment_entries = extract_comment_glossary(
        parsed["tree"],
        parsed["source_bytes"],
        str(source),
        graph_data,
    )
    manual_entries = [
        {
            "term": "userId",
            "kind": "variable",
            "file_path": str(source),
            "summary": "Manual summary.",
            "source": "manual",
        }
    ]

    nodes, relationships, qdrant_records = build_glossary_graph(
        graph_data,
        str(source),
        "typescript",
        manual_entries=manual_entries,
        comment_entries=comment_entries,
    )

    glossary = [node for node in nodes if node["label"] == "GlossaryEntry"]
    assert len(glossary) == 1
    assert glossary[0]["properties"]["summary"] == "Manual summary."
    assert glossary[0]["properties"]["source"] == "manual"
    assert relationships[0]["type"] == "HAS_GLOSSARY"
    assert qdrant_records[0]["node_type"] == "glossary_entry"
    assert qdrant_records[0]["summary"] == "Manual summary."
