"""Tests for yoke_core.domain.check_ac_presence."""

from __future__ import annotations

import io
import unittest
from contextlib import redirect_stderr, redirect_stdout
from unittest import mock

from yoke_core.domain import check_ac_presence as mod

TEST_ITEM_ID = 42
TEST_ITEM_REF = f"YOK-{TEST_ITEM_ID}"


class TestNormalizeId(unittest.TestCase):
    def test_sun_prefix(self) -> None:
        self.assertEqual(mod._normalize_item_id(TEST_ITEM_REF), TEST_ITEM_ID)

    def test_zero_padded(self) -> None:
        self.assertEqual(mod._normalize_item_id("YOK-007"), 7)
        self.assertEqual(mod._normalize_item_id("0042"), 42)

    def test_plain_number(self) -> None:
        self.assertEqual(mod._normalize_item_id("42"), 42)

    def test_invalid(self) -> None:
        self.assertIsNone(mod._normalize_item_id(""))
        self.assertIsNone(mod._normalize_item_id("abc"))
        self.assertIsNone(mod._normalize_item_id("YOK-"))


class TestExtractAcSection(unittest.TestCase):
    def test_basic_section(self) -> None:
        text = (
            "# Heading\n\n"
            "## Acceptance Criteria\n"
            "- [ ] First\n"
            "- [ ] Second\n"
            "\n"
            "## Another\n"
            "- [ ] Not counted\n"
        )
        section = mod.extract_ac_section(text)
        self.assertIn("- [ ] First", section)
        self.assertIn("- [ ] Second", section)
        self.assertNotIn("Not counted", section)

    def test_no_section_returns_empty(self) -> None:
        self.assertEqual(mod.extract_ac_section("# Heading\nNothing here\n"), "")

    def test_indented_heading_still_bounds_section(self) -> None:
        """uniformly indented ``## Acceptance Criteria`` and
        terminating ``## `` headings still resolve a bounded section.

        Heredoc-authored specs commonly get a uniform leading prefix on
        every line; the section extractor must see past that indent so the
        unlabeled-AC fallback path stays reachable.
        """
        text = (
            "    # Heading\n\n"
            "    ## Acceptance Criteria\n"
            "    - [ ] First\n"
            "    - [ ] Second\n"
            "\n"
            "    ## Another\n"
            "    - [ ] Not counted\n"
        )
        section = mod.extract_ac_section(text)
        self.assertIn("- [ ] First", section)
        self.assertIn("- [ ] Second", section)
        self.assertNotIn("Not counted", section)


class TestCountAcs(unittest.TestCase):
    def test_canonical_wins(self) -> None:
        text = (
            "## Acceptance Criteria\n"
            "- [ ] AC-1: First\n"
            "- [ ] AC-2: Second\n"
            "- [ ] Unlabeled\n"
        )
        canonical, unlabeled = mod.count_acs(text)
        self.assertEqual(canonical, 2)
        self.assertEqual(unlabeled, 0)

    def test_unlabeled_counted_only_without_canonical(self) -> None:
        text = (
            "## Acceptance Criteria\n"
            "- [ ] Only unlabeled\n"
            "- [ ] Another\n"
        )
        canonical, unlabeled = mod.count_acs(text)
        self.assertEqual(canonical, 0)
        self.assertEqual(unlabeled, 2)

    def test_canonical_outside_section(self) -> None:
        text = (
            "Intro\n"
            "- [ ] AC-1: Still counts\n"
            "\n"
            "## Something Else\n"
            "- [ ] not AC\n"
        )
        canonical, unlabeled = mod.count_acs(text)
        self.assertEqual(canonical, 1)
        self.assertEqual(unlabeled, 0)

    def test_nothing_present(self) -> None:
        self.assertEqual(mod.count_acs("# No checkboxes here"), (0, 0))

    def test_canonical_two_space_indent(self) -> None:
        """2-space indented canonical ACs (nested-list style)
        still count. CommonMark permits up to three leading spaces before a
        list marker, so the gate must accept them."""
        text = (
            "## Acceptance Criteria\n"
            "  - [ ] AC-1: First\n"
            "  - [ ] AC-2: Second\n"
            "  - [ ] AC-3: Third\n"
        )
        canonical, unlabeled = mod.count_acs(text)
        self.assertEqual(canonical, 3)
        self.assertEqual(unlabeled, 0)

    def test_canonical_four_space_indent(self) -> None:
        """4-space indented canonical ACs (heredoc artifact)
        still count. Strict CommonMark would treat this as an indented code
        block, but the gate's job is to detect author intent, not render
        Markdown."""
        text = (
            "    ## Acceptance Criteria\n"
            "    - [ ] AC-1: First\n"
            "    - [ ] AC-2: Second\n"
            "    - [ ] AC-3: Third\n"
        )
        canonical, unlabeled = mod.count_acs(text)
        self.assertEqual(canonical, 3)
        self.assertEqual(unlabeled, 0)

    def test_unlabeled_under_indented_heading(self) -> None:
        """unlabeled advisory path still works when the
        ``## Acceptance Criteria`` heading is indented."""
        text = (
            "    ## Acceptance Criteria\n"
            "    - [ ] foo\n"
            "    - [ ] bar\n"
        )
        canonical, unlabeled = mod.count_acs(text)
        self.assertEqual(canonical, 0)
        self.assertEqual(unlabeled, 2)


class TestMain(unittest.TestCase):
    def _run(self, argv: list[str]) -> tuple[int, str, str]:
        out_buf = io.StringIO()
        err_buf = io.StringIO()
        with redirect_stdout(out_buf), redirect_stderr(err_buf):
            rc = mod.main(argv)
        return rc, out_buf.getvalue(), err_buf.getvalue()

    def test_invalid_id_exits_2(self) -> None:
        rc, _, err = self._run(["abc"])
        self.assertEqual(rc, 2)
        self.assertIn("invalid item ID", err)

    def test_missing_item_exits_2(self) -> None:
        with mock.patch.object(mod, "_fetch_item_row", return_value=None):
            rc, _, err = self._run([TEST_ITEM_REF])
        self.assertEqual(rc, 2)
        self.assertIn("not found", err)

    def test_canonical_acs_exits_0_prints_count(self) -> None:
        spec = "## Acceptance Criteria\n- [ ] AC-1: foo\n- [ ] AC-2: bar\n"
        with mock.patch.object(
            mod,
            "_fetch_item_row",
            return_value=("My Item", spec, ""),
        ):
            rc, out, err = self._run(["YOK-5"])
        self.assertEqual(rc, 0)
        self.assertEqual(out.strip(), "2")
        self.assertEqual(err, "")

    def test_unlabeled_acs_exit_0_with_advisory(self) -> None:
        spec = "## Acceptance Criteria\n- [ ] foo\n- [ ] bar\n"
        with mock.patch.object(
            mod,
            "_fetch_item_row",
            return_value=("My Item", spec, ""),
        ):
            rc, out, err = self._run(["YOK-5"])
        self.assertEqual(rc, 0)
        self.assertEqual(out.strip(), "2")
        self.assertIn("unlabeled", err)

    def test_no_acs_exits_1(self) -> None:
        with mock.patch.object(
            mod,
            "_fetch_item_row",
            return_value=("My Item", "No checkboxes here", ""),
        ):
            rc, out, err = self._run(["YOK-5"])
        self.assertEqual(rc, 1)
        self.assertEqual(out, "")

    def test_falls_back_to_body_when_spec_empty(self) -> None:
        body = "## Acceptance Criteria\n- [ ] AC-1: From body\n"
        with mock.patch.object(
            mod,
            "_fetch_item_row",
            return_value=("My Item", "", body),
        ):
            rc, out, _ = self._run(["YOK-5"])
        self.assertEqual(rc, 0)
        self.assertEqual(out.strip(), "1")


if __name__ == "__main__":
    unittest.main()
