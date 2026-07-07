"""Tests for :mod:`render_body_section` — pure section extractor.

The extractor must:

* return the content between ``## <heading>`` and the next ``## ``,
* return ``None`` for a missing heading,
* keep nested ``### `` / ``#### `` headings inside the section,
* keep ``## `` lines that live inside a fenced code block,
* trim leading and trailing blank lines from the returned content.
"""

from __future__ import annotations

from yoke_core.domain.render_body_section import (
    extract_section,
    normalise_heading,
    strip_renderer_owned_section,
)


class TestNormaliseHeading:
    def test_strips_double_hash_prefix(self) -> None:
        assert normalise_heading("## File Budget") == "File Budget"

    def test_strips_double_hash_no_space(self) -> None:
        assert normalise_heading("##File Budget") == "File Budget"

    def test_accepts_bare_name(self) -> None:
        assert normalise_heading("File Budget") == "File Budget"

    def test_strips_surrounding_whitespace(self) -> None:
        assert normalise_heading("  ## File Budget  ") == "File Budget"


class TestExtractSection:
    def test_heading_match_returns_content(self) -> None:
        body = (
            "## Intro\n\nIntro text.\n\n"
            "## File Budget\n\nLine A.\nLine B.\n\n"
            "## Next\n\nNext text.\n"
        )
        assert extract_section(body, "## File Budget") == "Line A.\nLine B."

    def test_heading_match_accepts_bare_name(self) -> None:
        body = "## File Budget\n\nLine A.\n\n## Next\n\nNext.\n"
        assert extract_section(body, "File Budget") == "Line A."

    def test_missing_heading_returns_none(self) -> None:
        body = "## Intro\n\nIntro.\n\n## Next\n\nNext.\n"
        assert extract_section(body, "## File Budget") is None

    def test_missing_heading_returns_none_empty_body(self) -> None:
        assert extract_section("", "## File Budget") is None

    def test_next_top_level_heading_terminates_section(self) -> None:
        body = (
            "## File Budget\n\nFB content.\n\n"
            "## Verification\n\nVerify content.\n"
        )
        assert extract_section(body, "## File Budget") == "FB content."

    def test_nested_h3_h4_stay_inside_section(self) -> None:
        body = (
            "## File Budget\n\nFB intro.\n\n"
            "### Sub one\n\nSub content.\n\n"
            "#### Sub-sub\n\nDeeper.\n\n"
            "## Verification\n\nVerify.\n"
        )
        section = extract_section(body, "## File Budget")
        assert section is not None
        assert "FB intro." in section
        assert "### Sub one" in section
        assert "Sub content." in section
        assert "#### Sub-sub" in section
        assert "Deeper." in section
        assert "Verification" not in section

    def test_fenced_double_hash_line_does_not_terminate(self) -> None:
        body = (
            "## File Budget\n\nIntro.\n\n"
            "```\n## Not a heading inside fence\nstill in fence\n```\n\n"
            "After fence.\n\n"
            "## Verification\n\nVerify.\n"
        )
        section = extract_section(body, "## File Budget")
        assert section is not None
        assert "## Not a heading inside fence" in section
        assert "After fence." in section
        assert "Verify." not in section

    def test_tilde_fence_double_hash_line_does_not_terminate(self) -> None:
        body = (
            "## File Budget\n\nIntro.\n\n"
            "~~~\n## Inside tilde fence\n~~~\n\n"
            "After.\n\n"
            "## Verification\n\nVerify.\n"
        )
        section = extract_section(body, "## File Budget")
        assert section is not None
        assert "## Inside tilde fence" in section
        assert "After." in section

    def test_section_at_end_of_body_no_next_heading(self) -> None:
        body = "## Intro\n\nIntro.\n\n## File Budget\n\nFB content.\n"
        assert extract_section(body, "## File Budget") == "FB content."

    def test_empty_section_returns_empty_string(self) -> None:
        body = "## File Budget\n\n## Next\n\nNext.\n"
        assert extract_section(body, "## File Budget") == ""

    def test_case_sensitive_match(self) -> None:
        body = "## File Budget\n\nFB content.\n"
        # Different capitalisation does NOT match.
        assert extract_section(body, "## file budget") is None

    def test_heading_substring_does_not_match(self) -> None:
        # ``## File Budget Plan`` is NOT the same heading.
        body = (
            "## File Budget Plan\n\nNot the right section.\n\n"
            "## Next\n\nNext.\n"
        )
        assert extract_section(body, "## File Budget") is None

    def test_strips_leading_and_trailing_blank_lines(self) -> None:
        body = (
            "## File Budget\n\n\n\nLine A.\n\nLine B.\n\n\n\n"
            "## Next\n\nNext.\n"
        )
        section = extract_section(body, "## File Budget")
        assert section == "Line A.\n\nLine B."

    def test_empty_heading_argument_returns_none(self) -> None:
        body = "## File Budget\n\nFB.\n"
        assert extract_section(body, "") is None

    def test_only_hash_marks_argument_returns_none(self) -> None:
        body = "## File Budget\n\nFB.\n"
        assert extract_section(body, "##") is None


class TestStripRendererOwnedSection:
    def test_strips_named_block_until_next_top_level(self) -> None:
        content = (
            "Intro text.\n\n"
            "## Path Claims\n\nOperator copy.\n\n- a.py\n\n"
            "## File Budget\n\n- b.py\n"
        )
        result = strip_renderer_owned_section(content, "## Path Claims")
        assert "## Path Claims" not in result
        assert "Operator copy." not in result
        assert "## File Budget" in result
        assert "- b.py" in result
        assert "Intro text." in result

    def test_missing_heading_returns_content_unchanged(self) -> None:
        content = "Intro.\n\n## File Budget\n\n- a.py\n"
        assert strip_renderer_owned_section(content, "## Path Claims") == content

    def test_fenced_top_level_heading_inside_block_does_not_terminate(self) -> None:
        content = (
            "## Path Claims\n\n"
            "```\n## File Budget (inside fence)\n```\n\n"
            "After fence.\n\n"
            "## File Budget\n\nReal next section.\n"
        )
        result = strip_renderer_owned_section(content, "## Path Claims")
        assert "(inside fence)" not in result
        assert "After fence." not in result
        assert "Real next section." in result

    def test_nested_subheadings_stay_inside_stripped_block(self) -> None:
        content = (
            "## Path Claims\n\n### Claim 5\n\nBody.\n\n#### Sub\n\nDetail.\n\n"
            "## Next\n\nNext body.\n"
        )
        result = strip_renderer_owned_section(content, "## Path Claims")
        assert "Claim 5" not in result
        assert "Sub" not in result
        assert "## Next" in result
        assert "Next body." in result

    def test_block_at_end_of_content(self) -> None:
        content = "Lead.\n\n## Path Claims\n\nTrailing block.\n"
        result = strip_renderer_owned_section(content, "## Path Claims")
        assert "Trailing block." not in result
        assert "Lead." in result

    def test_empty_content_returned_unchanged(self) -> None:
        assert strip_renderer_owned_section("", "## Path Claims") == ""
