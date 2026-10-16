"""Watcher-capture completion state the hook client observes.

``yoke_contracts.watch_capture`` answers whether a capture file's owning
command is still running, on the machine that wrote the capture. The
watcher exit sentinel (``# watch_<kind> exit=<rc>``) is the authoritative
completion signal. It lands in the PROGRESS capture, never the RAW capture
(forensic fidelity), so a raw capture derives the ``.progress.`` sibling.
These tests run against real files.
"""

from __future__ import annotations

import os
import shutil
import tempfile
import time
import unittest
import uuid

from yoke_contracts.watch_capture import (
    EXIT_SENTINEL,
    capture_file_completed,
    capture_state,
)


def sentinel_line(kind: str, rc: int, raw_path: str) -> str:
    """Build the footer ``yoke_core.tools._watch_runner.run_watcher`` writes."""
    return f"# watch_{kind} exit={rc} raw={raw_path}\n"


class CapturePairHelpers:
    """Build real watcher raw+progress capture pairs in a temp dir.

    Plain mixin (not a ``TestCase``) so it is not collected on its own.
    """

    def _make_pair(self, kind: str = "merge") -> tuple[str, str]:
        # The nonce keeps parallel (pytest-xdist) workers from colliding.
        tmpdir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmpdir, ignore_errors=True)
        nonce = uuid.uuid4().hex
        raw = os.path.join(tmpdir, f"yoke-{kind}.raw.{nonce}.log")
        progress = os.path.join(tmpdir, f"yoke-{kind}.progress.{nonce}.log")
        return raw, progress

    @staticmethod
    def _write(path: str, content: str) -> None:
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(content)

    @staticmethod
    def _touch_old(path: str, age_seconds: float = 600) -> None:
        old = time.time() - age_seconds
        os.utime(path, (old, old))


class TestExitSentinel(unittest.TestCase):
    def test_matches_wrapper_footer(self) -> None:
        self.assertTrue(EXIT_SENTINEL.match(sentinel_line("pytest", 0, "/tmp/r")))

    def test_matches_negative_rc(self) -> None:
        self.assertTrue(EXIT_SENTINEL.match("# watch_merge exit=-15"))

    def test_ignores_ordinary_lines(self) -> None:
        self.assertIsNone(EXIT_SENTINEL.match("merge step 3 exit=0"))


class TestCaptureFileCompleted(CapturePairHelpers, unittest.TestCase):
    def test_raw_capture_sees_sentinel_in_progress_sibling(self) -> None:
        raw, progress = self._make_pair("merge")
        self._write(raw, "merge output line\n")  # raw never carries sentinel
        self._write(progress, "merge step 7e\n" + sentinel_line("merge", 0, raw))
        self.assertTrue(capture_file_completed(raw))

    def test_raw_capture_no_sentinel_yet(self) -> None:
        raw, progress = self._make_pair("merge")
        self._write(raw, "merge output line\n")
        self._write(progress, "merge step 3 in progress\n")
        self.assertFalse(capture_file_completed(raw))

    def test_progress_capture_sees_own_sentinel(self) -> None:
        _raw, progress = self._make_pair("doctor")
        self._write(progress, "HC-foo: PASS\n" + sentinel_line("doctor", 0, "x"))
        self.assertTrue(capture_file_completed(progress))

    def test_progress_capture_no_sentinel(self) -> None:
        _raw, progress = self._make_pair("doctor")
        self._write(progress, "HC-foo: PASS\n")
        self.assertFalse(capture_file_completed(progress))

    def test_missing_progress_sibling_is_not_completed(self) -> None:
        raw, _progress = self._make_pair("merge")
        self._write(raw, "merge output\n")
        self.assertFalse(capture_file_completed(raw))

    def test_sentinel_found_at_tail_of_large_capture(self) -> None:
        _raw, progress = self._make_pair("pytest")
        self._write(
            progress, "x" * 100 + "\n" * 20000 + sentinel_line("pytest", 1, "r")
        )
        self.assertTrue(capture_file_completed(progress))

    def test_plain_capture_without_sentinel(self) -> None:
        # Hand-authored mktemp capture: no `.raw.` marker, no sentinel.
        tmpdir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmpdir, ignore_errors=True)
        path = os.path.join(tmpdir, "yoke-cmd.plain.log")
        self._write(path, "some output\n")
        self.assertFalse(capture_file_completed(path))


class TestCaptureState(CapturePairHelpers, unittest.TestCase):
    def test_completed_capture_reports_completed_and_age(self) -> None:
        raw, progress = self._make_pair("merge")
        self._write(raw, "final merge output\n")
        self._write(progress, sentinel_line("merge", 0, raw))
        state = capture_state(raw)
        self.assertTrue(state["completed"])
        self.assertIsInstance(state["age_seconds"], float)
        self.assertLess(state["age_seconds"], 60)

    def test_midrun_capture_is_recent_and_not_completed(self) -> None:
        raw, progress = self._make_pair("merge")
        self._write(raw, "partial merge output\n")
        self._write(progress, "merge step 3\n")
        state = capture_state(raw)
        self.assertFalse(state["completed"])
        self.assertLess(state["age_seconds"], 60)

    def test_age_measured_from_mtime(self) -> None:
        raw, _progress = self._make_pair("merge")
        self._write(raw, "output\n")
        self._touch_old(raw, 600)
        state = capture_state(raw, now=os.stat(raw).st_mtime + 600)
        self.assertEqual(state, {"completed": False, "age_seconds": 600.0})

    def test_age_never_negative(self) -> None:
        raw, _progress = self._make_pair("merge")
        self._write(raw, "output\n")
        state = capture_state(raw, now=os.stat(raw).st_mtime - 30)
        self.assertEqual(state["age_seconds"], 0.0)

    def test_missing_capture_has_no_age(self) -> None:
        raw, _progress = self._make_pair("merge")
        self.assertEqual(capture_state(raw), {"completed": False, "age_seconds": None})


if __name__ == "__main__":
    unittest.main()
