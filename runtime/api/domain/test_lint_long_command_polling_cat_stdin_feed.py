"""Regression: ``cat <tmpfile> | <substantive consumer>`` is a stdin feed.

Field-note 8720: ``cat /tmp/yok-1882-impl-notes.md | yoke items section
upsert --item YOK-1882 --heading '## Implementation Notes' --stdin`` was
denied as a "manual progress peek". Semantics: ``cat`` is feeding the
tempfile's bytes to ``yoke`` via stdin (content payload), not peeking
at a long-running capture file.

The carve-out in ``_extract_peek_capture_file`` narrows the peek shape
to ``cat`` calls whose immediate pipe target is in the peek-verb set
(``cat | tail`` stays a peek; ``cat | yoke`` does not).
"""

from __future__ import annotations

import unittest

from yoke_core.domain import (
    lint_long_command_polling_evaluate as lint_eval,
)


class TestCatStdinFeedCarveOut(unittest.TestCase):
    def test_cat_pipe_yoke_stdin_is_not_peek(self) -> None:
        cmd = (
            "cat /tmp/yok-1882-impl-notes.md | yoke items section upsert "
            "--item YOK-1882 --heading '## Implementation Notes' --stdin"
        )
        self.assertIsNone(lint_eval._extract_peek_capture_file(cmd))

    def test_cat_pipe_python_module_is_not_peek(self) -> None:
        # Absolute-path consumer — basename check still classifies as
        # substantive.
        cmd = "cat /tmp/payload.json | /usr/bin/python3 -m foo"
        self.assertIsNone(lint_eval._extract_peek_capture_file(cmd))

    def test_cat_pipe_tail_stays_a_peek(self) -> None:
        # Sanity: peek-to-peek pipelines remain classified as peeks. The
        # broader extract-helpers test covers this too; restated here so
        # the carve-out's negative side stays anchored when the test file
        # is read in isolation.
        self.assertEqual(
            lint_eval._extract_peek_capture_file(
                "cat /tmp/run.log | tail -n 50"
            ),
            "/tmp/run.log",
        )


if __name__ == "__main__":
    unittest.main()
