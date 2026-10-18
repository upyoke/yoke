"""A task body's Files Touched section is its declared file list."""

from __future__ import annotations

import pytest

from yoke_core.domain.task_files_touched import (
    NO_FILES_LINE,
    STATE_MISSING,
    STATE_NO_FILES,
    STATE_PATHS,
    STATE_UNPARSEABLE,
    parse_files_touched,
    render_files_touched,
)


def test_bullets_name_paths_in_order_through_subheadings() -> None:
    body = (
        "# Task 001\n\n## Files Touched\n"
        "- create `src/new.py` — the parser\n"
        "### Tests\n- modify `tests/test_new.py`\n"
        "- `src/new.py` again\n\n## Watch Out For\n- `src/elsewhere.py`\n"
    )

    parsed = parse_files_touched(body)

    assert parsed.state == STATE_PATHS
    assert parsed.paths == ("src/new.py", "tests/test_new.py")
    assert parsed.problem() == ""


def test_no_files_line_is_an_explicit_empty_list() -> None:
    parsed = parse_files_touched(f"## Files Touched\n\n{NO_FILES_LINE}\n")

    assert parsed.state == STATE_NO_FILES
    assert parsed.paths == ()
    assert parsed.declared


def test_missing_section_is_reported() -> None:
    parsed = parse_files_touched("## Description\n- `src/a.py`\n")

    assert parsed.state == STATE_MISSING
    assert parsed.problem() == "has no ## Files Touched section"


@pytest.mark.parametrize(
    "section",
    [
        "TBD",
        "- the scheduler module",
        f"- modify `src/a.py`\n{NO_FILES_LINE}",
        f"{NO_FILES_LINE}\n\nAlso some notes.",
    ],
)
def test_pathless_or_contradictory_section_is_unparseable(section: str) -> None:
    parsed = parse_files_touched(f"## Files Touched\n{section}\n")

    assert parsed.state == STATE_UNPARSEABLE
    assert not parsed.declared
    assert NO_FILES_LINE in parsed.problem()


def test_rendered_section_parses_back_to_its_entries() -> None:
    section = render_files_touched([("create", "src/a.py"), ("delete", "docs/b.md")])

    assert section.startswith("## Files Touched\n\n- create `src/a.py`")
    assert parse_files_touched(section).paths == ("src/a.py", "docs/b.md")
    assert parse_files_touched(render_files_touched([])).state == STATE_NO_FILES
