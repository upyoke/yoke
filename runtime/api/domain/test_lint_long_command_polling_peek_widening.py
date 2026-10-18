"""Coverage for the widened peek-detection surface.

Sister test module of ``test_lint_long_command_polling_evaluate``;
focuses on the gaps that an unblocked-peek audit (session
``6e2f986d…``) demonstrated unblocked: the widened peek verb set,
``/private/tmp`` capture-file paths, the ``_count_prior_peeks_in_window``
``tool_use_id`` dedup fix and the permissive "first peek is free" branch.
The repeated-peek regression fixture lives in
``test_lint_long_command_polling_repeated_peek``.
"""

from __future__ import annotations

import unittest
from unittest import mock

from yoke_core.domain import lint_long_command_polling_evaluate as lint
from yoke_core.domain.lint_long_command_polling_extract import (
    _extract_peek_capture_file,
)
from yoke_core.domain.lint_long_command_polling_test_helpers import (
    CAPTURE_ROOTS as ROOTS,
    _bash_payload,
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


class TestEvaluateWidenedPeeksDuringBg(unittest.TestCase):
    """Widened verbs allow the first peek even when bg is active in session."""

    def setUp(self) -> None:
        self._mode_patch = mock.patch.object(
            lint, "_read_lint_mode", return_value="deny"
        )
        self._mode_patch.start()
        self.addCleanup(self._mode_patch.stop)

    def _bg_active_recent(self) -> list[tuple[str, str, str]]:
        return [
            (
                "tu-bg-kickoff",
                "2026-04-24T12:00:00",
                "sh test.sh > /tmp/foo.out 2>&1",
            ),
        ]

    def _assert_allows_first_peek(self, command: str) -> None:
        with (
            mock.patch.object(lint, "_owning_command_still_running", return_value=True),
            mock.patch.object(lint, "_db_available", return_value=True),
            mock.patch.object(
                lint, "_recent_bash_commands", return_value=self._bg_active_recent()
            ),
        ):
            result = lint.evaluate_payload(
                _bash_payload(command, tool_use_id="tu-current")
            )
        self.assertIsNone(result, f"command {command!r} should allow")

    def test_wc_first_peek_allowed(self) -> None:
        self._assert_allows_first_peek("wc -l /tmp/foo.out")

    def test_grep_first_peek_allowed(self) -> None:
        self._assert_allows_first_peek('grep -E "passed|failed" /tmp/foo.out')

    def test_ls_first_peek_allowed(self) -> None:
        self._assert_allows_first_peek("ls -la /tmp/foo.out")

    def test_stat_first_peek_allowed(self) -> None:
        self._assert_allows_first_peek("stat /tmp/foo.out")

    def test_awk_first_peek_allowed(self) -> None:
        self._assert_allows_first_peek("awk '/PASS/{print}' /tmp/foo.out")

    def test_private_tmp_first_peek_allowed(self) -> None:
        path = "/private/tmp/claude-501/abc/tasks/b8ly752ok.output"
        self._assert_allows_first_peek(f"cat {path}")

    def test_no_bg_first_peek_allowed(self) -> None:
        # Without a prior same-capture peek, the first peek is still allowed.
        with (
            mock.patch.object(lint, "_owning_command_still_running", return_value=True),
            mock.patch.object(lint, "_db_available", return_value=True),
            mock.patch.object(lint, "_recent_bash_commands", return_value=[]),
        ):
            self.assertIsNone(
                lint.evaluate_payload(
                    _bash_payload("tail -80 /tmp/foo.out", tool_use_id="tu-current")
                )
            )


class TestDedupFix(unittest.TestCase):
    """``_count_prior_peeks_in_window`` dedupes on ``tool_use_id``.

    The legacy implementation deduped on ``turn_id``; production
    ``observe_pre`` envelopes leave ``turn_id`` null, so the count
    silently dropped to zero and the second-peek branch never fired.
    The fix dedupes on ``tool_use_id`` (always populated by
    ``observe_pre``); these tests exercise that contract by passing
    fixtures whose first tuple element (``tool_use_id``) is populated
    even when production-shaped ``turn_id`` would be empty.
    """

    def test_count_with_populated_tool_use_id(self) -> None:
        recent = [
            (
                "tu-prior-peek",
                "2026-04-24T12:00:00",
                "tail -80 /tmp/foo.out",
            ),
        ]
        # dedup keys on tool_use_id; not skipped because the field is
        # populated AND distinct from current_tool_use_id.
        self.assertEqual(
            lint._count_prior_peeks_in_window(
                recent,
                "/tmp/foo.out",
                "tu-current",
                ROOTS,
            ),
            1,
        )

    def test_count_skips_empty_tool_use_id(self) -> None:
        # If a row's tool_use_id IS empty (production reality before the
        # contract fix), the dedup still skips it. The test exists to
        # document the existing skip behaviour: the fix's value is that
        # production rows now carry a populated tool_use_id.
        recent = [
            ("", "2026-04-24T12:00:00", "tail -80 /tmp/foo.out"),
        ]
        self.assertEqual(
            lint._count_prior_peeks_in_window(
                recent,
                "/tmp/foo.out",
                "tu-current",
                ROOTS,
            ),
            0,
        )

    def test_count_skips_self(self) -> None:
        recent = [
            ("tu-current", "2026-04-24T12:00:00", "tail -80 /tmp/foo.out"),
        ]
        self.assertEqual(
            lint._count_prior_peeks_in_window(
                recent,
                "/tmp/foo.out",
                "tu-current",
                ROOTS,
            ),
            0,
        )

    def test_count_within_window(self) -> None:
        recent = [
            ("tu-1", "2026-04-24T12:00:01", "git status"),
            ("tu-2", "2026-04-24T12:00:02", "tail -80 /tmp/foo.out"),
            ("tu-3", "2026-04-24T12:00:03", "tail -80 /tmp/foo.out"),
        ]
        self.assertEqual(
            lint._count_prior_peeks_in_window(
                recent,
                "/tmp/foo.out",
                "tu-current",
                ROOTS,
            ),
            2,
        )

    def test_count_outside_5_turn_window(self) -> None:
        # 6 distinct prior tool_use_ids; the oldest peek is beyond the
        # window of 5 distinct dedup IDs.
        recent = [
            ("tu-6", "", "git diff"),
            ("tu-5", "", "ls"),
            ("tu-4", "", "pwd"),
            ("tu-3", "", "git log"),
            ("tu-2", "", "git branch"),
            ("tu-1", "", "tail -80 /tmp/foo.out"),
        ]
        self.assertEqual(
            lint._count_prior_peeks_in_window(
                recent,
                "/tmp/foo.out",
                "tu-current",
                ROOTS,
            ),
            0,
        )


if __name__ == "__main__":
    unittest.main()
