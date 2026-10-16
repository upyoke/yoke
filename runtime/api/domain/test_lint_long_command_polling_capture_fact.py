"""End-to-end polling verdicts from a client capture fact built on real files.

The hook client observes each capture with
:func:`yoke_contracts.watch_capture.capture_state` and ships it as the
``CAPTURE_FILES_KEY`` fact; ``evaluate_payload`` reads only that fact. These
tests build the fact from real watcher capture pairs to prove:

  (a) a post-completion peek on a finished watcher passes WITHOUT a
      suppression token, even though the raw capture was just written, and
  (b) a repeated mid-run peek (no sentinel yet) is still denied.
"""

from __future__ import annotations

import os
import unittest
from unittest import mock

from runtime.api.test_watch_capture import CapturePairHelpers, sentinel_line
from yoke_contracts.watch_capture import capture_state
from yoke_core.domain import lint_long_command_polling_evaluate as lint
from yoke_core.domain.lint_long_command_polling_extract import (
    _extract_peek_capture_file,
)
from yoke_core.domain.lint_long_command_polling_test_helpers import (
    _bash_payload,
)


class TestEvaluatePayloadFromObservedCapture(CapturePairHelpers, unittest.TestCase):
    def setUp(self) -> None:
        patch = mock.patch.object(lint, "_read_lint_mode", return_value="deny")
        patch.start()
        self.addCleanup(patch.stop)

    def _peek_payload(self, raw: str) -> dict:
        command = f"tail -80 {raw}"
        roots = (os.path.dirname(raw),)
        # Guard: the peek extractor must see this path, else an "allowed"
        # result would be a false pass.
        self.assertEqual(_extract_peek_capture_file(command, roots), raw)
        return _bash_payload(
            command,
            tool_use_id="tu-peek",
            roots=roots,
            captures={raw: capture_state(raw)},
        )

    def _evaluate_after_prior_peek(self, raw: str):
        recent = [("tu-prior", "2026-05-28T17:00:00", f"tail -80 {raw}")]
        with (
            mock.patch.object(lint, "_db_available", return_value=True),
            mock.patch.object(lint, "_recent_bash_commands", return_value=recent),
        ):
            return lint.evaluate_payload(self._peek_payload(raw))

    def test_post_completion_peek_allowed_without_suppression(self) -> None:
        raw, progress = self._make_pair("merge")
        self._write(raw, "final merge output\n")
        self._write(progress, sentinel_line("merge", 0, raw))
        self.assertIsNone(
            self._evaluate_after_prior_peek(raw),
            "post-completion peek must be allowed without suppression",
        )

    def test_midrun_repeated_peek_still_denied(self) -> None:
        raw, progress = self._make_pair("merge")
        self._write(raw, "partial merge output\n")
        self._write(progress, "merge step 3\n")  # no sentinel yet
        result = self._evaluate_after_prior_peek(raw)
        self.assertIsNotNone(result, "mid-run peek must still be denied")
        assert result is not None
        verdict, _reason, ctx = result
        self.assertEqual(verdict, "deny")
        self.assertEqual(ctx.get("capture_file"), raw)

    def test_stale_capture_without_sentinel_allowed(self) -> None:
        raw, progress = self._make_pair("merge")
        self._write(raw, "output\n")
        self._write(progress, "merge step 3\n")
        self._touch_old(raw)
        self.assertIsNone(self._evaluate_after_prior_peek(raw))


if __name__ == "__main__":
    unittest.main()
