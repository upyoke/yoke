"""Tests for yoke_core.domain.normalize_ac_labels."""

from __future__ import annotations

import io
import os
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from unittest import mock

from yoke_core.domain import normalize_ac_labels as mod


class TestHighestExistingAc(unittest.TestCase):
    def test_empty(self) -> None:
        self.assertEqual(mod._highest_existing_ac("no acs here"), 0)

    def test_picks_highest(self) -> None:
        text = (
            "- [ ] AC-1: first\n"
            "- [ ] AC-7: seventh\n"
            "- [ ] AC-3: third\n"
        )
        self.assertEqual(mod._highest_existing_ac(text), 7)


class TestNormalize(unittest.TestCase):
    def test_unlabeled_under_section_gets_numbered(self) -> None:
        text = (
            "# Title\n"
            "\n"
            "## Acceptance Criteria\n"
            "- [ ] First\n"
            "- [ ] Second\n"
            "\n"
            "## Other Section\n"
            "- [ ] Not normalized\n"
        )
        normalized, count = mod.normalize(text)
        self.assertEqual(count, 2)
        self.assertIn("- [ ] AC-1: First", normalized)
        self.assertIn("- [ ] AC-2: Second", normalized)
        # Outside-section checkbox left alone
        self.assertIn("- [ ] Not normalized", normalized)

    def test_canonical_acs_preserved(self) -> None:
        text = (
            "## Acceptance Criteria\n"
            "- [ ] AC-1: existing\n"
            "- [ ] new-unlabeled\n"
        )
        normalized, count = mod.normalize(text)
        self.assertEqual(count, 1)
        self.assertIn("- [ ] AC-1: existing", normalized)
        self.assertIn("- [ ] AC-2: new-unlabeled", normalized)

    def test_continues_from_highest(self) -> None:
        text = (
            "## Acceptance Criteria\n"
            "- [ ] AC-5: existing\n"
            "- [ ] fresh one\n"
        )
        normalized, count = mod.normalize(text)
        self.assertEqual(count, 1)
        self.assertIn("- [ ] AC-6: fresh one", normalized)

    def test_no_section_no_changes(self) -> None:
        text = "# Title\n- [ ] random checkbox\n"
        normalized, count = mod.normalize(text)
        self.assertEqual(count, 0)
        self.assertIn("- [ ] random checkbox", normalized)

    def test_section_exit_via_next_heading(self) -> None:
        text = (
            "## Acceptance Criteria\n"
            "- [ ] first\n"
            "\n"
            "## Done\n"
            "- [ ] outside\n"
        )
        normalized, count = mod.normalize(text)
        self.assertEqual(count, 1)
        self.assertIn("- [ ] AC-1: first", normalized)
        self.assertIn("- [ ] outside", normalized)
        self.assertNotIn("AC-2", normalized)


class TestMain(unittest.TestCase):
    def _run_stdin(self, stdin_text: str) -> tuple[int, str, str]:
        out_buf = io.StringIO()
        err_buf = io.StringIO()
        fake_stdin = io.StringIO(stdin_text)
        with mock.patch.object(mod.sys, "stdin", fake_stdin), \
             redirect_stdout(out_buf), redirect_stderr(err_buf):
            rc = mod.main([])
        return rc, out_buf.getvalue(), err_buf.getvalue()

    def test_stdin_normalization(self) -> None:
        text = "## Acceptance Criteria\n- [ ] foo\n- [ ] bar\n"
        rc, out, err = self._run_stdin(text)
        self.assertEqual(rc, 0)
        self.assertIn("- [ ] AC-1: foo", out)
        self.assertIn("- [ ] AC-2: bar", out)
        self.assertIn("Normalized 2", err)

    def test_stdin_no_changes_no_stderr(self) -> None:
        rc, _, err = self._run_stdin("# No ACs here\n")
        self.assertEqual(rc, 0)
        self.assertEqual(err, "")

    def test_file_input(self) -> None:
        with tempfile.NamedTemporaryFile(
            "w",
            delete=False,
            suffix=".md",
        ) as handle:
            handle.write("## Acceptance Criteria\n- [ ] solo\n")
            path = handle.name
        try:
            out_buf = io.StringIO()
            err_buf = io.StringIO()
            with redirect_stdout(out_buf), redirect_stderr(err_buf):
                rc = mod.main(["--file", path])
            self.assertEqual(rc, 0)
            self.assertIn("- [ ] AC-1: solo", out_buf.getvalue())
            self.assertIn("Normalized 1", err_buf.getvalue())
        finally:
            os.unlink(path)

    def test_missing_file_exits_2(self) -> None:
        err_buf = io.StringIO()
        with redirect_stderr(err_buf):
            rc = mod.main(["--file", "/nonexistent/path/foo.md"])
        self.assertEqual(rc, 2)
        self.assertIn("not found", err_buf.getvalue())


if __name__ == "__main__":
    unittest.main()
