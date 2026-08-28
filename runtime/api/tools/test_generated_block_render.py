"""Tests for yoke_core.tools.generated_block_render.

The marker mechanics are shared by every generated-block family, so they are
exercised here once rather than per family.
"""

from __future__ import annotations

import pathlib
import tempfile
import unittest
from unittest import mock

from yoke_core.tools import generated_block_render as gbr


SLUG = "test-family"
BEGIN = gbr.begin_marker(SLUG)
END = gbr.end_marker(SLUG)


def _wrap(body: str) -> str:
    return f"# Title\n\nIntro.\n\n{BEGIN}\n{body}{END}\n\nTrailer.\n"


class TestRewriteBetweenMarkers(unittest.TestCase):
    def test_valid_pair_rewrites_content(self) -> None:
        original = _wrap("OLD\n")
        new = gbr.rewrite_between_markers(original, "NEW\n", slug=SLUG)
        self.assertIsNotNone(new)
        self.assertIn("NEW", new)
        self.assertNotIn("OLD", new)
        self.assertIn(BEGIN, new)
        self.assertIn(END, new)

    def test_orphan_begin_returns_none(self) -> None:
        original = f"{BEGIN}\nbody-without-end\n"
        self.assertIsNone(
            gbr.rewrite_between_markers(original, "REPLACEMENT\n", slug=SLUG)
        )

    def test_orphan_end_returns_none(self) -> None:
        original = f"body-without-begin\n{END}\n"
        self.assertIsNone(
            gbr.rewrite_between_markers(original, "REPLACEMENT\n", slug=SLUG)
        )

    def test_end_before_begin_returns_none(self) -> None:
        original = f"{END}\nstuff\n{BEGIN}\n"
        self.assertIsNone(
            gbr.rewrite_between_markers(original, "REPLACEMENT\n", slug=SLUG)
        )

    def test_two_begin_markers_unsupported(self) -> None:
        original = f"{BEGIN}\nA\n{BEGIN}\nB\n{END}\n"
        self.assertIsNone(
            gbr.rewrite_between_markers(original, "REPLACEMENT\n", slug=SLUG)
        )

    def test_no_markers_at_all_returns_none(self) -> None:
        self.assertIsNone(
            gbr.rewrite_between_markers(
            "plain content\n", "REPLACEMENT\n", slug=SLUG,
        )
        )


class TestScanForOrphans(unittest.TestCase):
    def test_clean_returns_none(self) -> None:
        self.assertIsNone(gbr.scan_for_orphans(_wrap("body\n"), slug=SLUG))
        self.assertIsNone(gbr.scan_for_orphans("no markers here\n", slug=SLUG))

    def test_orphan_begin(self) -> None:
        self.assertEqual(
            gbr.scan_for_orphans(f"{BEGIN}\nbody\n", slug=SLUG),
            "BEGIN marker without matching END",
        )

    def test_orphan_end(self) -> None:
        self.assertEqual(
            gbr.scan_for_orphans(f"body\n{END}\n", slug=SLUG),
            "END marker without matching BEGIN",
        )

    def test_multiple_pairs(self) -> None:
        text = _wrap("A\n") + _wrap("B\n")
        self.assertEqual(
            gbr.scan_for_orphans(text, slug=SLUG),
            "multiple marker pairs in one file (not supported)",
        )



class TestRenderBlocks(unittest.TestCase):
    def test_missing_file_is_reported_not_raised(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            result = gbr.render_blocks(
                pathlib.Path(tmp),
                slug=SLUG,
                inventory=("absent.md",),
                content_for_path=lambda _p: "BODY\n",
            )
        self.assertEqual(len(result.missing_files), 1)
        self.assertTrue(result.ok)

    def test_orphan_marker_is_a_hard_failure(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            (root / "a.md").write_text(f"{BEGIN}\nbody\n", encoding="utf-8")
            result = gbr.render_blocks(
                root,
                slug=SLUG,
                inventory=("a.md",),
                content_for_path=lambda _p: "BODY\n",
            )
        self.assertFalse(result.ok)
        self.assertIn("a.md", result.orphan_marker_errors[0])

    def test_check_mode_does_not_write(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            original = _wrap("OLD\n")
            (root / "a.md").write_text(original, encoding="utf-8")
            result = gbr.render_blocks(
                root,
                slug=SLUG,
                inventory=("a.md",),
                content_for_path=lambda _p: "NEW\n",
                check=True,
            )
            self.assertEqual(len(result.changed), 1)
            self.assertEqual(
                (root / "a.md").read_text(encoding="utf-8"), original,
            )

    def test_render_writes_under_workspace_authority(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            (root / "a.md").write_text(_wrap("OLD\n"), encoding="utf-8")
            with mock.patch.object(
                gbr, "assert_target_under_session_work_authority",
            ) as guard:
                gbr.render_blocks(
                    root,
                    slug=SLUG,
                    inventory=("a.md",),
                    content_for_path=lambda _p: "NEW\n",
                )
            guard.assert_called_once()
            body = (root / "a.md").read_text(encoding="utf-8")
        self.assertIn("NEW", body)
        self.assertNotIn("OLD", body)

    def test_summary_names_the_family_and_repair(self) -> None:
        result = gbr.RenderResult(
            changed=(gbr.FileRenderOutcome(path="a.md", state="rendered"),),
            unchanged=(),
            missing_markers=(),
            missing_files=(),
            orphan_marker_errors=(),
        )
        summary = gbr.format_drift_summary(
            result, check=True, family_label="widgets", repair_command="fix-it",
        )
        self.assertIn("widgets renderer would change", summary)
        self.assertIn("fix-it", summary)
        self.assertIn("a.md", summary)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
