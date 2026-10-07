"""Structural validator for Feature-page and Document-page bodies.

Used by both the LLM generator (`generator.py`, to reject/retry a bad
completion) and the dashboard's edit endpoints (`PUT /apps/{app}/docs/{id}`)
so a human edit is held to a sane shape. Frontmatter is server-owned and
validated separately via `FeatureFrontmatter`/`DocumentFrontmatter` (pydantic);
this module only checks the body a person or the LLM actually writes.

``_generic_checks`` holds every rule shared between the two page kinds
(size limits, fence tracking, H1, setext headings, raw HTML, links);
`validate_feature_body` layers the fixed 8-section template on top, while
`validate_document_body` (free-form Markdown, only an H1 required) uses it
as-is with looser link/setext handling.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from pydantic import ValidationError

from code_vector_graph.ingestion.okf.features.models import FeatureFrontmatter, ValidationIssue, ValidationResult
from code_vector_graph.ingestion.okf.features.template import (
    REQUIRED_H2,
    NONE_SENTINEL,
    extract_title,
    iter_h2_headings,
    parse_sections,
    split_frontmatter,
)

MAX_BODY_CHARS = 60_000
MAX_DOCUMENT_CHARS = 200_000
MAX_LINE_CHARS = 2_000

_FENCE_RE = re.compile(r"^\s*```")
_MERMAID_FENCE_RE = re.compile(r"^\s*```mermaid\s*$")
_RAW_HTML_RE = re.compile(r"<\s*/?\s*[a-zA-Z!]")
_SETEXT_RE = re.compile(r"^(=+|-{2,})\s*$")
_H1_LINE_RE = re.compile(r"^#\s+\S")
_LIST_ITEM_RE = re.compile(r"^\s*[-*+]\s+\S")
_NUMBERED_RE = re.compile(r"^\s*\d+\.\s+\S")
_LINK_RE = re.compile(r"\[[^\]]*\]\(([^)]+)\)")
_BUNDLE_LINK_RE = re.compile(r"^/(feature|file|document|class|function|method|interface|typealias)/[A-Za-z0-9._-]+\.md$")


def _normalize(text: str) -> str:
    return text.replace("\r\n", "\n").replace("\r", "\n")


def _table_header_ok(section_text: str) -> bool:
    for line in section_text.splitlines():
        line = line.strip()
        if not line.startswith("|"):
            continue
        cells = [c.strip().lower() for c in line.strip("|").split("|")]
        if cells == ["kind", "name", "location"]:
            return True
    return False


@dataclass
class _GenericChecks:
    """Result of the checks shared by every page kind, plus the fence-span
    lookup later, kind-specific rules need to skip content inside fences."""

    body: str
    lines: list[str]
    errors: list[ValidationIssue] = field(default_factory=list)
    warnings: list[ValidationIssue] = field(default_factory=list)
    fence_spans: list[tuple[int, int]] = field(default_factory=list)
    mermaid_fences: int = 0

    def in_fence(self, line_no: int) -> bool:
        return any(start <= line_no <= end for start, end in self.fence_spans)


def _generic_checks(
    body: str,
    *,
    title: str | None,
    known_paths: set[str] | None,
    max_body_chars: int,
    setext_is_error: bool,
    relative_link_is_error: bool,
) -> _GenericChecks:
    body = _normalize(body)
    lines = body.splitlines()
    result = _GenericChecks(body=body, lines=lines)

    if len(body) > max_body_chars:
        result.errors.append(ValidationIssue("too_long", f"Document is {len(body)} chars (max {max_body_chars})."))

    for i, line in enumerate(lines, start=1):
        if len(line) > MAX_LINE_CHARS:
            result.errors.append(ValidationIssue("too_long", f"Line {i} exceeds {MAX_LINE_CHARS} characters.", line=i))

    # --- fenced code blocks: track spans so later rules can skip inside them ---
    open_fence_at: int | None = None
    for i, line in enumerate(lines, start=1):
        if _FENCE_RE.match(line):
            if open_fence_at is None:
                open_fence_at = i
                if _MERMAID_FENCE_RE.match(line):
                    result.mermaid_fences += 1
            else:
                result.fence_spans.append((open_fence_at, i))
                open_fence_at = None
    if open_fence_at is not None:
        result.errors.append(ValidationIssue("unclosed_fence", "A ``` code fence is never closed.", line=open_fence_at))

    # --- H1 ---
    h1 = extract_title(body)
    if h1 is None:
        result.errors.append(ValidationIssue("missing_h1", "Document must start with a single '# Title' line."))
    elif title and h1 != title:
        result.errors.append(ValidationIssue("mismatch_h1", f"H1 '{h1}' does not match the page title '{title}'."))

    h1_lines = [i for i, line in enumerate(lines, start=1) if not result.in_fence(i) and _H1_LINE_RE.match(line)]
    if len(h1_lines) > 1:
        result.errors.append(ValidationIssue("multiple_h1", "Only one '# ' (H1) heading is allowed.", line=h1_lines[1]))

    # --- setext headings (outside fences; table separator rows contain '|') ---
    for i in range(len(lines) - 1):
        if result.in_fence(i + 2):
            continue
        text_line, underline = lines[i], lines[i + 1]
        if (
            text_line.strip()
            and not text_line.lstrip().startswith("#")
            and "|" not in underline
            and _SETEXT_RE.match(underline)
        ):
            issue = ValidationIssue("setext_heading", "Use ATX ('#') headings only, not setext underlines.", line=i + 2)
            (result.errors if setext_is_error else result.warnings).append(issue)

    # --- raw HTML outside fences ---
    for i, line in enumerate(lines, start=1):
        if result.in_fence(i):
            continue
        if _RAW_HTML_RE.search(line):
            result.errors.append(ValidationIssue("raw_html", "Raw HTML is not allowed outside a code fence.", line=i))

    # --- links ---
    for i, line in enumerate(lines, start=1):
        if result.in_fence(i):
            continue
        for target in _LINK_RE.findall(line):
            target = target.strip()
            if target.startswith("#") or target.startswith("http://") or target.startswith("https://") or target.startswith("mailto:"):
                continue
            if _BUNDLE_LINK_RE.match(target):
                if known_paths is not None and target not in known_paths:
                    result.warnings.append(
                        ValidationIssue("unresolved_link", f"Link target '{target}' does not resolve.", line=i)
                    )
                continue
            issue = ValidationIssue(
                "bad_link", f"Link target '{target}' is not an anchor, http(s)/mailto URL, or bundle path.", line=i
            )
            (result.errors if relative_link_is_error else result.warnings).append(issue)

    return result


def validate_feature_body(
    body: str,
    *,
    title: str | None = None,
    known_paths: set[str] | None = None,
) -> ValidationResult:
    """Validate a Feature-page body against the fixed 8-section template.

    ``title`` (when given) must match the body's H1. ``known_paths`` (when
    given) is the set of bundle-relative link targets (e.g.
    ``"/feature/other.md"``) that actually exist; unresolved bundle links are
    a warning, not an error, since the API has no bundle to check against.
    """
    generic = _generic_checks(
        body, title=title, known_paths=known_paths,
        max_body_chars=MAX_BODY_CHARS, setext_is_error=True, relative_link_is_error=True,
    )
    body, lines = generic.body, generic.lines
    errors, warnings = generic.errors, generic.warnings

    if generic.mermaid_fences > 1:
        errors.append(ValidationIssue("mermaid_count", "At most one ```mermaid block is allowed."))

    # --- H2 coverage / order ---
    headings = [(ln, name) for ln, name in iter_h2_headings(body) if not generic.in_fence(ln)]
    seen: set[str] = set()
    for ln, name in headings:
        if name not in REQUIRED_H2 or name in seen:
            errors.append(ValidationIssue("h2_extra", f"Unexpected or duplicate heading '## {name}'.", line=ln))
        else:
            seen.add(name)
    for name in REQUIRED_H2:
        if name not in seen:
            errors.append(ValidationIssue("h2_missing", f"Missing required section '## {name}'."))

    first_seen_order = list(dict.fromkeys(name for _, name in headings if name in seen))
    expected_order = [name for name in REQUIRED_H2 if name in seen]
    if first_seen_order != expected_order:
        errors.append(ValidationIssue("h2_order", "Sections are out of order; expected: " + ", ".join(REQUIRED_H2)))

    sections = parse_sections(body)

    for name in REQUIRED_H2:
        if name == "Open Questions":
            continue
        if not sections.get(name, "").strip():
            errors.append(ValidationIssue("section_empty", f"Section '## {name}' must not be empty."))

    business_rules = sections.get("Business Rules", "")
    if business_rules.strip() and not any(_LIST_ITEM_RE.match(line) for line in business_rules.splitlines()):
        errors.append(
            ValidationIssue("business_rules_list", "'## Business Rules' must contain at least one '- ' list item.")
        )

    process_flow = sections.get("Process Flow", "")
    numbered_count = sum(1 for line in process_flow.splitlines() if _NUMBERED_RE.match(line))
    if numbered_count < 2:
        errors.append(
            ValidationIssue(
                "flow_steps",
                "'## Process Flow' must contain at least two numbered steps ('1. ...', '2. ...').",
            )
        )

    entry_points = sections.get("Entry Points", "")
    if entry_points.strip() != NONE_SENTINEL and not _table_header_ok(entry_points):
        errors.append(
            ValidationIssue(
                "entry_points_table",
                "'## Entry Points' must contain a table with header '| Kind | Name | Location |', "
                f"or exactly '{NONE_SENTINEL}'.",
            )
        )

    return ValidationResult(ok=not errors, errors=errors, warnings=warnings)


def validate_document_body(
    body: str,
    *,
    title: str | None = None,
    known_paths: set[str] | None = None,
) -> ValidationResult:
    """Validate a free-form, human-authored Document-page body.

    Only an H1 title is required; unlike Feature pages there is no fixed
    section template, multiple ```mermaid blocks are allowed, and a setext
    heading or a relative (non-anchor/http(s)/bundle) link is a warning
    rather than an error, since ordinary prose has no bundle to check
    against and setext headings are common Markdown, just discouraged here.
    """
    generic = _generic_checks(
        body, title=title, known_paths=known_paths,
        max_body_chars=MAX_DOCUMENT_CHARS, setext_is_error=False, relative_link_is_error=False,
    )
    errors, warnings = generic.errors, generic.warnings

    h1 = extract_title(generic.body)
    if h1 is not None:
        non_blank_lines = [ln for ln in generic.lines if ln.strip()]
        if len(non_blank_lines) <= 1:
            warnings.append(ValidationIssue("empty_body", "Document has a title but no body content."))

    return ValidationResult(ok=not errors, errors=errors, warnings=warnings)


def validate_feature_page(text: str) -> ValidationResult:
    """Validate a full page (frontmatter + body), e.g. before writing it to the
    bundle at build time."""
    try:
        fm_dict, body = split_frontmatter(text)
    except ValueError as exc:
        return ValidationResult(ok=False, errors=[ValidationIssue("bad_frontmatter", str(exc))])
    try:
        fm = FeatureFrontmatter.model_validate(fm_dict)
    except ValidationError as exc:
        return ValidationResult(ok=False, errors=[ValidationIssue("bad_frontmatter", str(exc))])
    return validate_feature_body(body, title=fm.title)
