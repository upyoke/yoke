"""Replacing one Markdown section leaves the rest of the document alone."""

from __future__ import annotations

import pytest

from yoke_core.domain.strategy_doc_sections import (
    StrategyDocSectionMissingError,
    find_section,
    replace_section,
    section_headings,
)


DOC = """# Current plan

Intro prose.

## Live status

Stale line one.
Stale line two.

### In flight

An old subsection.

## Next up

Untouched tail.
"""


def test_a_section_is_replaced_without_disturbing_its_neighbours() -> None:
    result = replace_section(DOC, "Live status", "Fresh line.")

    assert "## Live status\n\nFresh line." in result
    assert "Intro prose." in result
    assert "## Next up\n\nUntouched tail." in result
    assert "Stale line one." not in result


def test_a_section_takes_its_deeper_subsections_with_it() -> None:
    """A nested heading belongs to the section it sits under."""
    result = replace_section(DOC, "Live status", "Fresh line.")

    assert "### In flight" not in result
    assert "An old subsection." not in result


def test_the_heading_is_matched_case_insensitively_and_kept_as_written() -> None:
    result = replace_section(DOC, "LIVE STATUS", "Fresh line.")

    assert "## Live status" in result
    assert "## LIVE STATUS" not in result


def test_the_last_section_replaces_without_leaving_a_trailing_gap() -> None:
    result = replace_section(DOC, "Next up", "New tail.")

    assert result.endswith("## Next up\n\nNew tail.\n")


def test_a_heading_the_document_lacks_is_refused_with_the_ones_it_has() -> None:
    """Appending instead would report success for a misspelled heading."""
    with pytest.raises(StrategyDocSectionMissingError) as caught:
        replace_section(DOC, "Live Statuses", "Fresh line.")

    message = str(caught.value)
    assert "Live Statuses" in message
    assert "Live status" in message
    assert "Next up" in message


def test_the_span_ends_at_the_next_heading_of_the_same_level() -> None:
    span = find_section(DOC, "Live status")

    assert span is not None
    assert DOC.splitlines()[span.heading_index] == "## Live status"
    assert DOC.splitlines()[span.body_end] == "## Next up"


def test_headings_are_reported_in_document_order() -> None:
    assert section_headings(DOC) == (
        "Current plan",
        "Live status",
        "In flight",
        "Next up",
    )
