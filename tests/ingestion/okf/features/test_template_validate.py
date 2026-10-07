"""Tests for the Feature-page template renderer and structural validator."""

from code_vector_graph.ingestion.okf.features.models import Entity, EntryPoint, FeatureDoc, FeatureFrontmatter
from code_vector_graph.ingestion.okf.features.template import (
    REQUIRED_H2,
    compose_page,
    extract_title,
    parse_sections,
    render_feature_markdown,
    split_frontmatter,
)
from code_vector_graph.ingestion.okf.features.validate import validate_feature_body, validate_feature_page


def _full_doc(**overrides) -> FeatureDoc:
    base = dict(
        title="Tender Deadline Reminders",
        description="Sends reminder emails before a tender's submission deadline.",
        overview="Reminds bidders before deadlines so submissions aren't missed.",
        business_rules=["A reminder is sent 48h before the deadline."],
        process_flow=["Cron tick checks upcoming deadlines.", "MailService sends the reminder."],
        entities=[Entity(name="Tender", description="fields used: deadline, status")],
        entry_points=[EntryPoint(kind="Cron", name="remindUpcomingDeadlines", file="src/jobs/reminders.ts", line=12)],
        dependencies=["MailService"],
        edge_cases=["Deadline in the past: skipped with a warning log."],
        open_questions=[],
        tags=["email"],
    )
    base.update(overrides)
    return FeatureDoc(**base)


def _valid_body(**doc_overrides) -> str:
    doc = _full_doc(**doc_overrides)
    return render_feature_markdown(doc.title, doc)


def _frontmatter(**overrides) -> FeatureFrontmatter:
    base = dict(
        title="Tender Deadline Reminders",
        slug="tender-deadline-reminders",
        description="Sends reminder emails before a tender's submission deadline.",
        app="onebid",
        repo="backend-api",
        feature_id="4b1c1111-2222-3333-4444-555566667777",
        kind="user-facing",
        members_hash="3fa9c2d1e0b7a654",
        member_files=["src/jobs/reminders.ts"],
        member_ids=["id1"],
        source="llm",
        generated_at="2026-08-28T10:00:00+00:00",
        model="deepseek-v4-pro",
        tags=["email"],
    )
    base.update(overrides)
    return FeatureFrontmatter(**base)


# --- rendering -------------------------------------------------------------


def test_render_produces_all_required_sections_in_order():
    body = _valid_body()
    headings = list(parse_sections(body).keys())
    assert headings == list(REQUIRED_H2)


def test_render_is_valid():
    body = _valid_body()
    result = validate_feature_body(body, title="Tender Deadline Reminders")
    assert result.ok, result.errors


def test_render_empty_lists_use_safe_fallbacks_and_still_validate():
    body = _valid_body(
        overview="",
        business_rules=[],
        process_flow=[],
        entities=[],
        entry_points=[],
        dependencies=[],
        edge_cases=[],
        open_questions=[],
    )
    result = validate_feature_body(body, title="Tender Deadline Reminders")
    assert result.ok, result.errors


def test_render_open_questions_can_stay_empty():
    body = _valid_body(open_questions=[])
    assert "_None._" in parse_sections(body)["Open Questions"]


# --- compose / split round-trip --------------------------------------------


def test_compose_split_round_trip():
    fm = _frontmatter()
    body = _valid_body()
    page = compose_page(fm, body)

    fm_dict, body_back = split_frontmatter(page)
    assert fm_dict["slug"] == "tender-deadline-reminders"
    assert fm_dict["feature_id"] == fm.feature_id
    assert body_back.strip() == body.strip()

    result = validate_feature_page(page)
    assert result.ok, result.errors


def test_split_frontmatter_rejects_missing_marker():
    try:
        split_frontmatter("# just a body, no frontmatter\n")
        assert False, "expected ValueError"
    except ValueError:
        pass


def test_split_frontmatter_rejects_unterminated_block():
    try:
        split_frontmatter("---\ntype: Feature\n")
        assert False, "expected ValueError"
    except ValueError:
        pass


def test_validate_feature_page_rejects_bad_frontmatter_type():
    body = _valid_body()
    fm = _frontmatter()
    page = compose_page(fm, body).replace("type: Feature", "type: NotAFeature")
    result = validate_feature_page(page)
    assert not result.ok
    assert any(e.code == "bad_frontmatter" for e in result.errors)


# --- CRLF normalisation ------------------------------------------------------


def test_crlf_body_normalises_and_validates():
    body = _valid_body().replace("\n", "\r\n")
    result = validate_feature_body(body, title="Tender Deadline Reminders")
    assert result.ok, result.errors


# --- one failing fixture per structural rule --------------------------------


def test_missing_h1():
    body = _valid_body().split("\n", 1)[1]  # drop the "# Title" line
    result = validate_feature_body(body, title="Tender Deadline Reminders")
    assert any(e.code == "missing_h1" for e in result.errors)


def test_mismatch_h1():
    body = _valid_body()
    result = validate_feature_body(body, title="Some Other Title")
    assert any(e.code == "mismatch_h1" for e in result.errors)


def test_multiple_h1():
    body = _valid_body() + "\n# Another Title\n"
    result = validate_feature_body(body, title="Tender Deadline Reminders")
    assert any(e.code == "multiple_h1" for e in result.errors)


def test_h2_missing():
    body = _valid_body().replace("## Open Questions\n_None._\n", "")
    result = validate_feature_body(body, title="Tender Deadline Reminders")
    assert any(e.code == "h2_missing" for e in result.errors)


def test_h2_extra():
    body = _valid_body() + "\n## Surprise Section\nwhoops\n"
    result = validate_feature_body(body, title="Tender Deadline Reminders")
    assert any(e.code == "h2_extra" for e in result.errors)


def test_h2_order():
    body = _valid_body()
    overview_block = "## Overview\nReminds bidders before deadlines so submissions aren't missed."
    rules_block = "## Business Rules\n- A reminder is sent 48h before the deadline."
    placeholder = "## __PLACEHOLDER__"
    swapped = body.replace(overview_block, placeholder).replace(rules_block, overview_block).replace(
        placeholder, rules_block
    )
    result = validate_feature_body(swapped, title="Tender Deadline Reminders")
    assert any(e.code == "h2_order" for e in result.errors)


def test_setext_heading_rejected():
    body = _valid_body().replace(
        "## Overview\nReminds bidders before deadlines so submissions aren't missed.\n",
        "## Overview\nReminds bidders before deadlines so submissions aren't missed.\nSubheading\n---\n",
    )
    result = validate_feature_body(body, title="Tender Deadline Reminders")
    assert any(e.code == "setext_heading" for e in result.errors)


def test_section_empty():
    body = _valid_body().replace(
        "## Key Entities & Data\n- **Tender** — fields used: deadline, status\n",
        "## Key Entities & Data\n\n",
    )
    result = validate_feature_body(body, title="Tender Deadline Reminders")
    assert any(e.code == "section_empty" for e in result.errors)


def test_business_rules_requires_list_item():
    body = _valid_body().replace(
        "## Business Rules\n- A reminder is sent 48h before the deadline.",
        "## Business Rules\nJust prose, no bullets.",
    )
    result = validate_feature_body(body, title="Tender Deadline Reminders")
    assert any(e.code == "business_rules_list" for e in result.errors)


def test_flow_steps_requires_two_numbered_lines():
    # The renderer itself guarantees >=2 steps, so exercise the validator
    # directly against a hand-crafted body that violates the rule.
    body = _valid_body().replace(
        "## Process Flow\n1. Cron tick checks upcoming deadlines.\n2. MailService sends the reminder.",
        "## Process Flow\n1. Only one step.",
    )
    result = validate_feature_body(body, title="Tender Deadline Reminders")
    assert any(e.code == "flow_steps" for e in result.errors)


def test_entry_points_table_header_required():
    body = _valid_body().replace(
        "| Kind | Name | Location |\n|------|------|----------|\n"
        "| Cron | `remindUpcomingDeadlines` | `src/jobs/reminders.ts:12` |",
        "| Foo | Bar |\n|---|---|\n| a | b |",
    )
    result = validate_feature_body(body, title="Tender Deadline Reminders")
    assert any(e.code == "entry_points_table" for e in result.errors)


def test_entry_points_none_sentinel_is_accepted():
    body = _valid_body(entry_points=[])
    result = validate_feature_body(body, title="Tender Deadline Reminders")
    assert result.ok, result.errors


def test_raw_html_rejected_outside_fence():
    body = _valid_body().replace(
        "Reminds bidders before deadlines so submissions aren't missed.",
        "Reminds bidders <b>before</b> deadlines.",
    )
    result = validate_feature_body(body, title="Tender Deadline Reminders")
    assert any(e.code == "raw_html" for e in result.errors)


def test_raw_html_allowed_inside_fence():
    body = _valid_body(mermaid="flowchart TD\n  A[<div>ok inside fence</div>]")
    result = validate_feature_body(body, title="Tender Deadline Reminders")
    assert not any(e.code == "raw_html" for e in result.errors)


def test_unclosed_fence_rejected():
    body = _valid_body() + "\n```\nnever closed\n"
    result = validate_feature_body(body, title="Tender Deadline Reminders")
    assert any(e.code == "unclosed_fence" for e in result.errors)


def test_mermaid_count_limited_to_one():
    body = _valid_body(mermaid="flowchart TD\n  A --> B")
    body += "\n```mermaid\nflowchart TD\n  C --> D\n```\n"
    result = validate_feature_body(body, title="Tender Deadline Reminders")
    assert any(e.code == "mermaid_count" for e in result.errors)


def test_bad_link_rejected():
    body = _valid_body().replace(
        "Reminds bidders before deadlines so submissions aren't missed.",
        "See [docs](javascript:alert(1)) for more.",
    )
    result = validate_feature_body(body, title="Tender Deadline Reminders")
    assert any(e.code == "bad_link" for e in result.errors)


def test_bundle_link_ok_without_known_paths():
    body = _valid_body().replace(
        "Reminds bidders before deadlines so submissions aren't missed.",
        "See [other feature](/feature/other-feature.md) for context.",
    )
    result = validate_feature_body(body, title="Tender Deadline Reminders")
    assert result.ok, result.errors


def test_unresolved_bundle_link_is_a_warning_not_an_error():
    body = _valid_body().replace(
        "Reminds bidders before deadlines so submissions aren't missed.",
        "See [ghost](/feature/does-not-exist.md) for context.",
    )
    result = validate_feature_body(body, title="Tender Deadline Reminders", known_paths={"/feature/real.md"})
    assert result.ok, result.errors
    assert any(w.code == "unresolved_link" for w in result.warnings)


def test_too_long_body_rejected():
    body = _valid_body() + ("x" * 100_000)
    result = validate_feature_body(body, title="Tender Deadline Reminders")
    assert any(e.code == "too_long" for e in result.errors)


def test_extract_title_returns_none_without_h1():
    assert extract_title("## Overview\nhi\n") is None
    assert extract_title("# Title\n\n## Overview\nhi\n") == "Title"
