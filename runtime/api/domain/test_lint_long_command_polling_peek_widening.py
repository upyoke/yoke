"""Capture read extraction used by sleep polling detection."""

from __future__ import annotations

import unittest

from yoke_core.domain.lint_long_command_polling_extract import (
    _extract_peek_capture_file,
)
from yoke_core.domain.lint_long_command_polling_test_helpers import (
    CAPTURE_ROOTS as ROOTS,
)


class TestExtractPeekVerbWidening(unittest.TestCase):
    """The pure regex extractor recognises every widened peek verb."""

    def test_tail_head_cat_still_extract(self) -> None:
        for verb in ("tail -80", "head -10", "cat"):
            self.assertEqual(
                _extract_peek_capture_file(f"{verb} /tmp/foo.out", ROOTS),
                "/tmp/foo.out",
                f"verb {verb!r} did not match",
            )

    def test_widened_verbs_extract(self) -> None:
        cases = [
            "wc -l",
            "grep -E pat",
            "egrep pat",
            "fgrep pat",
            "rg pat",
            "ls -la",
            "awk '/PASS/'",
            "sed -n 1,5p",
            "less",
            "more",
            "file",
            "stat",
            "nl",
            "cut -d, -f1",
            "sort",
            "uniq",
        ]
        for prefix in cases:
            with self.subTest(verb=prefix):
                self.assertEqual(
                    _extract_peek_capture_file(f"{prefix} /tmp/foo.out", ROOTS),
                    "/tmp/foo.out",
                )

    def test_private_tmp_prefix_extracts(self) -> None:
        # Claude Code TaskOutput artifacts live under /private/tmp/...
        path = "/private/tmp/claude-501/abc123def/tasks/b8ly752ok.output"
        self.assertEqual(
            _extract_peek_capture_file(f"cat {path}", ROOTS),
            path,
        )
        self.assertEqual(
            _extract_peek_capture_file(f"grep pat {path}", ROOTS),
            path,
        )

    def test_redirect_still_treated_as_kickoff(self) -> None:
        self.assertIsNone(
            _extract_peek_capture_file("sh test.sh > /tmp/foo.out 2>&1", ROOTS)
        )

    def test_kickoff_with_redirect_not_a_peek(self) -> None:
        # `cmd > /tmp/...` even when it also tails earlier in the line:
        # the redirect makes it a kickoff. Never count it as a peek.
        self.assertIsNone(
            _extract_peek_capture_file(
                "tail -80 /tmp/old.out && sh test.sh > /tmp/new.out 2>&1",
                ROOTS,
            )
        )

    def test_flag_attached_verb_not_a_peek(self) -> None:
        # ``--body-file /tmp/x.md`` is a CLI argument, not a ``file`` peek.
        # The ``-`` immediately before ``file`` rejects the match. Same shape
        # for ``--stat=...``, ``--head=...``, ``--cat=...`` and any other
        # flag that happens to end in a peek verb. Regression for an
        # ouroboros report where ``epic review-insert --body-file
        # /tmp/yok1843-task2-review.md`` was wrongly denied as a peek.
        cases = [
            "python3 -m yoke_core.cli.db_router epic review-insert --body-file /tmp/r.md",
            "python3 -m yoke_core.cli.db_router items update 1 spec --body-file /tmp/x.md",
            "cmd --stat=/tmp/foo.out",
            "cmd --head=/tmp/foo.out",
        ]
        for command in cases:
            with self.subTest(command=command):
                self.assertIsNone(
                    _extract_peek_capture_file(command, ROOTS),
                    f"command {command!r} should not be classified as a peek",
                )

    def test_path_attached_verb_not_a_peek(self) -> None:
        # A path ending in a verb name (``/usr/local/bin/file``,
        # ``some/dir/stat``) is not a peek. The ``/`` immediately before
        # the verb rejects the match.
        self.assertIsNone(
            _extract_peek_capture_file("/usr/bin/file /tmp/foo.out", ROOTS)
        )
        self.assertIsNone(
            _extract_peek_capture_file("/usr/local/bin/stat /tmp/foo.out", ROOTS)
        )
