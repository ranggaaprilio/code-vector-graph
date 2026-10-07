"""Feature-page Markdown template: render an LLM `FeatureDoc` to a body,
compose/split the full page (YAML frontmatter + body), and parse sections
back out of a body.

The frontmatter is server-owned (identity, hashes, timestamps) and is never
edited directly by a human; only the body — the H1 title plus the eight
required `## ` sections — is user-editable. `render.py`'s `_frontmatter`/
`_section` helpers are concept-page-shaped (one heading per page type) and
don't fit a fixed multi-section template, so this module is Feature-specific.
"""

from __future__ import annotations

import re
from typing import Iterable

import yaml

from typing import Any

from code_vector_graph.ingestion.okf.features.models import Entity, EntryPoint, FeatureDoc, FeatureFrontmatter

REQUIRED_H2: tuple[str, ...] = (
    "Overview",
    "Business Rules",
    "Process Flow",
    "Key Entities & Data",
    "Entry Points",
    "Dependencies & Integrations",
    "Edge Cases & Error Handling",
    "Open Questions",
)

NONE_SENTINEL = "_None identified._"
NONE_QUESTIONS_SENTINEL = "_None._"

_H1_RE = re.compile(r"^#\s+(.+?)\s*$")
_H2_RE = re.compile(r"^##\s+(.+?)\s*$")


def _bullets(items: Iterable[str]) -> str:
    cleaned = [i.strip() for i in items if i and i.strip()]
    if not cleaned:
        return NONE_SENTINEL
    return "\n".join(f"- {i}" for i in cleaned)


def _bullets_required(items: Iterable[str], fallback: str) -> str:
    """Like `_bullets`, but guarantees at least one real list item."""
    cleaned = [i.strip() for i in items if i and i.strip()]
    if not cleaned:
        cleaned = [fallback]
    return "\n".join(f"- {i}" for i in cleaned)


def _numbered(items: Iterable[str]) -> str:
    cleaned = [i.strip() for i in items if i and i.strip()]
    if len(cleaned) < 2:
        cleaned = [
            "No explicit steps were identified in the source.",
            "See the entry points below for how this feature is triggered.",
        ]
    return "\n".join(f"{i + 1}. {text}" for i, text in enumerate(cleaned))


def _entities_block(entities: list[Entity]) -> str:
    named = [e for e in entities if e.name and e.name.strip()]
    if not named:
        return NONE_SENTINEL
    lines = []
    for e in named:
        desc = f" — {e.description.strip()}" if e.description and e.description.strip() else ""
        lines.append(f"- **{e.name.strip()}**{desc}")
    return "\n".join(lines)


def _entry_points_table(entry_points: list[EntryPoint]) -> str:
    rows = [ep for ep in entry_points if ep.name and ep.name.strip()]
    if not rows:
        return NONE_SENTINEL
    lines = ["| Kind | Name | Location |", "|------|------|----------|"]
    for ep in rows:
        location = (ep.file or "").strip()
        if ep.line:
            location += f":{ep.line}"
        lines.append(f"| {(ep.kind or '-').strip() or '-'} | `{ep.name.strip()}` | `{location}` |")
    return "\n".join(lines)


def render_feature_markdown(title: str, doc: FeatureDoc) -> str:
    """Render a `FeatureDoc` into the body: H1 title + the 8 required sections,
    in order. Every section always has non-blank content (see `validate.py`)."""
    overview = (doc.overview or "").strip() or NONE_SENTINEL
    mermaid_block = f"\n\n```mermaid\n{doc.mermaid.strip()}\n```" if doc.mermaid and doc.mermaid.strip() else ""
    parts = [
        f"# {title}",
        "",
        "## Overview",
        overview,
        "",
        "## Business Rules",
        _bullets_required(doc.business_rules, "No explicit business rules were identified in the source."),
        "",
        "## Process Flow",
        _numbered(doc.process_flow) + mermaid_block,
        "",
        "## Key Entities & Data",
        _entities_block(doc.entities),
        "",
        "## Entry Points",
        _entry_points_table(doc.entry_points),
        "",
        "## Dependencies & Integrations",
        _bullets(doc.dependencies),
        "",
        "## Edge Cases & Error Handling",
        _bullets(doc.edge_cases),
        "",
        "## Open Questions",
        "\n".join(f"- {q.strip()}" for q in doc.open_questions if q and q.strip()) or NONE_QUESTIONS_SENTINEL,
        "",
    ]
    return "\n".join(parts).rstrip() + "\n"


def compose_page(fm: FeatureFrontmatter | Any, body: str) -> str:
    """Compose the full page (YAML frontmatter + body) for export/GET.

    Accepts any frontmatter model with a ``model_dump`` (e.g.
    ``DocumentFrontmatter``) — this function only serializes it, it does not
    depend on any Feature-specific field.
    """
    fm_dict = fm.model_dump(mode="json", exclude_none=True)
    yaml_text = yaml.safe_dump(fm_dict, sort_keys=False, allow_unicode=True, default_flow_style=False)
    return f"---\n{yaml_text}---\n\n{body.strip()}\n"


def split_frontmatter(text: str) -> tuple[dict, str]:
    """Split a page into (frontmatter dict, body). Raises ValueError if malformed."""
    if not text.startswith("---"):
        raise ValueError("page does not start with YAML frontmatter ('---')")
    parts = text.split("---", 2)
    if len(parts) < 3:
        raise ValueError("page frontmatter is not terminated with a second '---'")
    try:
        fm = yaml.safe_load(parts[1]) or {}
    except yaml.YAMLError as exc:
        raise ValueError(f"invalid YAML frontmatter: {exc}") from exc
    if not isinstance(fm, dict):
        raise ValueError("frontmatter must be a YAML mapping")
    return fm, parts[2].strip() + "\n"


def extract_title(body: str) -> str | None:
    """The H1 title, if the body's first non-blank line is a '# ' heading."""
    for line in body.splitlines():
        if not line.strip():
            continue
        m = _H1_RE.match(line)
        return m.group(1).strip() if m else None
    return None


def iter_h2_headings(body: str) -> list[tuple[int, str]]:
    """(1-indexed line number, heading text) for every ATX H2 line, in order."""
    return [(i, m.group(1).strip()) for i, line in enumerate(body.splitlines(), start=1) if (m := _H2_RE.match(line))]


def parse_sections(body: str) -> dict[str, str]:
    """Split the body into {H2 heading: section text} (text between headings)."""
    lines = body.splitlines()
    headings = iter_h2_headings(body)
    sections: dict[str, str] = {}
    for idx, (line_no, name) in enumerate(headings):
        end = headings[idx + 1][0] - 1 if idx + 1 < len(headings) else len(lines)
        sections[name] = "\n".join(lines[line_no:end]).strip()
    return sections


_HEADING_RE = re.compile(r"^\s{0,3}#{1,6}\s")


def first_paragraph(body: str, max_chars: int = 300) -> str:
    """The first non-blank, non-heading, non-fenced-code paragraph in
    ``body``, whitespace-collapsed and truncated with an ellipsis.

    Used to derive a Document page's short ``description`` from its
    freeform content (there is no separate summary field for humans to
    fill in, unlike a Feature page's LLM-authored description).
    """
    lines = body.replace("\r\n", "\n").replace("\r", "\n").splitlines()
    paragraph: list[str] = []
    in_fence = False
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("```"):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        if not stripped or _HEADING_RE.match(line):
            if paragraph:
                break
            continue
        paragraph.append(stripped)
    text = " ".join(paragraph).strip()
    text = re.sub(r"\s+", " ", text)
    if len(text) > max_chars:
        text = text[: max_chars - 1].rstrip() + "\u2026"
    return text
