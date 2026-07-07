"""Watcher-completion detection coverage for the polling lint.

Regression for ouroboros 8857 / 8873: a watcher-backed background command
whose Monitor had already emitted its exit sentinel was misclassified as
still running, so the single sanctioned post-completion ``tail -80
<raw-capture>`` was denied and required the ``# lint:no-polling-check``
suppression token.

The watcher exit sentinel (``# watch_<kind> exit=<rc>``) is the
authoritative completion signal. It lands in the PROGRESS capture, never
the RAW capture (forensic fidelity), so a raw-capture peek derives the
``.progress.`` sibling. These tests exercise the REAL
``_owning_command_still_running`` + ``capture_file_completed`` against
real files — the completion helpers are NOT mocked — to prove:

  (a) a post-completion peek on a finished watcher passes WITHOUT a
      suppression token, and
  (b) a mid-run peek (no sentinel yet) on a still-running watcher is still
      denied.
"""

from __future__ import annotations

import os
import shutil
import tempfile
import time
import unittest
import uuid
from unittest import mock

from yoke_core.domain import lint_long_command_polling_evaluate as lint
from yoke_core.domain.lint_long_command_polling_completion import (
    capture_file_completed,
)
from yoke_core.domain.lint_long_command_polling_extract import (
    _extract_peek_capture_file,
)
from yoke_core.domain.lint_long_command_polling_test_helpers import (
    _bash_payload,
)


def _sentinel_line(kind: str, rc: int, raw_path: str) -> str:
    """Build a realistic wrapper exit-sentinel line.

    Mirrors the footer literal that
    ``yoke_core.tools._watch_runner.run_watcher`` writes and that
    ``yoke_core.tools.watch_tail.EXIT_SENTINEL`` matches. The lint reads
    the canonical regex from ``watch_tail``; this fixture asserts the line
    that regex must recognise.
    """
    return f"# watch_{kind} exit={rc} raw={raw_path}\n"


class _CapturePairHelpers:
    """Build real watcher raw+progress capture pairs in a temp dir.

    Plain mixin (not a ``TestCase``) so it is not collected on its own;
    ``self.addCleanup`` / ``self.assert*`` resolve through the concrete
    ``TestCase`` it is combined with.
    """

    def _make_pair(self, kind: str = "merge") -> tuple[str, str]:
        # mkdtemp lands under tempfile.gettempdir(), which the peek-extractor
        # regex recognises as a scratch root; the nonce keeps parallel
        # (pytest-xdist) workers from colliding.
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
    def _touch_recent(path: str) -> None:
        now = time.time()
        os.utime(path, (now, now))

    @staticmethod
    def _touch_old(path: str, age_seconds: float = 600) -> None:
        old = time.time() - age_seconds
        os.utime(path, (old, old))


class TestCaptureFileCompleted(_CapturePairHelpers, unittest.TestCase):
    """Unit tests on ``capture_file_completed`` sentinel detection."""

    def test_raw_peek_sees_sentinel_in_progress_sibling(self) -> None:
        raw, progress = self._make_pair("merge")
        self._write(raw, "merge output line\n")  # raw never carries sentinel
        self._write(
            progress, "merge step 7e\n" + _sentinel_line("merge", 0, raw)
        )
        self.assertTrue(capture_file_completed(raw))

    def test_raw_peek_no_sentinel_yet(self) -> None:
        raw, progress = self._make_pair("merge")
        self._write(raw, "merge output line\n")
        self._write(progress, "merge step 3 in progress\n")  # no sentinel
        self.assertFalse(capture_file_completed(raw))

    def test_progress_peek_direct_sees_sentinel(self) -> None:
        _raw, progress = self._make_pair("doctor")
        self._write(
            progress, "HC-foo: PASS\n" + _sentinel_line("doctor", 0, "x")
        )
        self.assertTrue(capture_file_completed(progress))

    def test_progress_peek_direct_no_sentinel(self) -> None:
        _raw, progress = self._make_pair("doctor")
        self._write(progress, "HC-foo: PASS\n")
        self.assertFalse(capture_file_completed(progress))

    def test_missing_progress_sibling_is_not_completed(self) -> None:
        raw, _progress = self._make_pair("merge")
        self._write(raw, "merge output\n")  # progress sibling never created
        self.assertFalse(capture_file_completed(raw))

    def test_non_watcher_path_without_sentinel(self) -> None:
        # Hand-authored mktemp capture: no `.raw.` marker, no sentinel.
        tmpdir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmpdir, ignore_errors=True)
        path = os.path.join(tmpdir, "yoke-cmd.plain.log")
        self._write(path, "some output\n")
        self.assertFalse(capture_file_completed(path))


class TestOwningCommandStillRunning(_CapturePairHelpers, unittest.TestCase):
    """The authoritative sentinel overrides the recent-mtime heuristic."""

    def test_completed_recent_mtime_not_running(self) -> None:
        # THE FIX: sentinel present + recent mtime -> NOT running.
        raw, progress = self._make_pair("merge")
        self._write(raw, "final merge output\n")
        self._write(progress, _sentinel_line("merge", 0, raw))
        self._touch_recent(raw)
        self._touch_recent(progress)
        self.assertFalse(lint._owning_command_still_running(raw))

    def test_midrun_recent_mtime_still_running(self) -> None:
        # No sentinel + recent mtime -> still running (heuristic preserved).
        raw, progress = self._make_pair("merge")
        self._write(raw, "partial merge output\n")
        self._write(progress, "merge step 3\n")
        self._touch_recent(raw)
        self._touch_recent(progress)
        self.assertTrue(lint._owning_command_still_running(raw))

    def test_old_mtime_no_sentinel_not_running(self) -> None:
        # Historical mtime path unchanged: stale capture -> not running.
        raw, progress = self._make_pair("merge")
        self._write(raw, "output\n")
        self._write(progress, "merge step 3\n")
        self._touch_old(raw)
        self._touch_old(progress)
        self.assertFalse(lint._owning_command_still_running(raw))


class TestEvaluatePayloadCompletion(_CapturePairHelpers, unittest.TestCase):
    """End-to-end ``evaluate_payload`` AC coverage (deny mode)."""

    def setUp(self) -> None:
        self._mode_patch = mock.patch.object(
            lint, "_read_lint_mode", return_value="deny"
        )
        self._mode_patch.start()
        self.addCleanup(self._mode_patch.stop)

    def test_post_completion_peek_allowed_without_suppression(self) -> None:
        # AC (a): finished watcher (sentinel in progress sibling) with a
        # freshly-written raw capture. `tail -80 <raw>` must be ALLOWED
        # with no suppression token.
        raw, progress = self._make_pair("merge")
        self._write(raw, "final merge output\n")
        self._write(progress, _sentinel_line("merge", 0, raw))
        self._touch_recent(raw)
        self._touch_recent(progress)
        command = f"tail -80 {raw}"
        # Guard: the peek extractor must actually see this path, else the
        # "allowed" result would be a false pass.
        self.assertEqual(_extract_peek_capture_file(command), raw)
        self.assertNotIn("# lint:no-polling-check", command)
        result = lint.evaluate_payload(
            _bash_payload(command, tool_use_id="tu-peek")
        )
        self.assertIsNone(
            result,
            "post-completion peek must be allowed without suppression",
        )

    def test_midrun_repeated_peek_still_denied(self) -> None:
        # AC (b): still-running watcher (no sentinel) + recent mtime + a
        # prior same-capture peek. The repeated `tail -80 <raw>` is denied.
        raw, progress = self._make_pair("merge")
        self._write(raw, "partial merge output\n")
        self._write(progress, "merge step 3\n")  # no sentinel yet
        self._touch_recent(raw)
        self._touch_recent(progress)
        recent = [("tu-prior", "2026-05-28T17:00:00", f"tail -80 {raw}")]
        command = f"tail -80 {raw}"
        self.assertEqual(_extract_peek_capture_file(command), raw)
        with mock.patch.object(
            lint, "_db_available", return_value=True
        ), mock.patch.object(
            lint, "_recent_bash_commands", return_value=recent
        ):
            result = lint.evaluate_payload(
                _bash_payload(command, tool_use_id="tu-peek")
            )
        self.assertIsNotNone(result, "mid-run peek must still be denied")
        assert result is not None
        verdict, _reason, _ctx = result
        self.assertEqual(verdict, "deny")


if __name__ == "__main__":
    unittest.main()
