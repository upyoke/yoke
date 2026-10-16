"""``lint_long_command_polling_evaluate.evaluate_payload`` cases.

Split out of ``test_lint_long_command_polling.py`` to keep authored files
under the 350-line limit. ``evaluate_payload`` and every helper it calls
live in the evaluate sibling — the ``lint`` alias here points there.
Capture state comes from the client fact the payload builders attach.
"""

from __future__ import annotations

import unittest
from unittest import mock

from yoke_core.domain import lint_long_command_polling_evaluate as lint
from yoke_core.domain.lint_long_command_polling_extract import (
    _extract_background_capture_files,
)
from yoke_core.domain.lint_long_command_polling_test_helpers import (
    CAPTURE_ROOTS as ROOTS,
    FINISHED,
    RUNNING,
    STALE,
    _bash_payload,
    _non_bash_payload,
)

LIVE = {"/tmp/foo.out": RUNNING}
_PRIOR_PEEK = [("turn-0", "2026-04-24T12:00:00", "tail -80 /tmp/foo.out")]


class TestExtractHelpers(unittest.TestCase):
    def test_background_capture_files_from_watcher_args(self) -> None:
        command = (
            "python3 -m yoke_core.tools.watch_pytest "
            "--raw-capture /tmp/raw.log "
            "--progress-capture=/tmp/progress.log -- runtime/api/"
        )
        self.assertEqual(
            _extract_background_capture_files(command, ROOTS),
            ["/tmp/raw.log", "/tmp/progress.log"],
        )

    def test_background_capture_files_accept_any_watcher_arg_path(self) -> None:
        # The watcher-arg regex has no root anchor — the --raw-capture flag
        # is the discriminator — so it holds even with no client roots.
        command = (
            "python3 -m yoke_core.tools.watch_pytest "
            "--raw-capture /var/folders/jb/abc/T/yoke-pytest.raw.log "
            "--progress-capture=/var/folders/jb/abc/T/yoke-pytest.progress.log "
            "-- runtime/api/"
        )
        self.assertEqual(
            _extract_background_capture_files(command, ()),
            [
                "/var/folders/jb/abc/T/yoke-pytest.raw.log",
                "/var/folders/jb/abc/T/yoke-pytest.progress.log",
            ],
        )

    def test_background_capture_files_from_redirect_under_client_root(self) -> None:
        # `cmd > <client tempdir>/foo.log 2>&1` is a kickoff, not a peek.
        # The redirect regex accepts whatever roots the client reported.
        client_tmp = "/var/folders/jb/abc/T"
        command = f"sh test.sh > {client_tmp}/yoke-cmd.example.log 2>&1"
        self.assertEqual(
            _extract_background_capture_files(command, (client_tmp,)),
            [f"{client_tmp}/yoke-cmd.example.log"],
        )
        self.assertEqual(_extract_background_capture_files(command, ROOTS), [])


class TestEvaluatePayload(unittest.TestCase):
    def setUp(self) -> None:
        # Default: no DB, warn mode, no recent events. Each test overrides as
        # needed via mock.patch.
        self._mode_patch = mock.patch.object(
            lint, "_read_lint_mode", return_value="warn"
        )
        self._mode_patch.start()
        self.addCleanup(self._mode_patch.stop)

    def test_git_status_allowed(self) -> None:
        self.assertIsNone(lint.evaluate_payload(_bash_payload("git status")))

    def test_suppressed_peek_allowed(self) -> None:
        self.assertIsNone(
            lint.evaluate_payload(
                _bash_payload("tail -80 /tmp/foo.out  # lint:no-polling-check")
            )
        )

    def test_sleep_short_cadence_flagged(self) -> None:
        result = lint.evaluate_payload(
            _bash_payload("sleep 10 && tail -20 /tmp/foo.out")
        )
        self.assertIsNotNone(result)
        assert result is not None
        verdict, reason, _ctx = result
        self.assertEqual(verdict, "warn")
        self.assertIn("sleep", reason.lower())

    def test_sleep_cadence_at_floor_allowed(self) -> None:
        # sleep 60 is exactly the fallback cadence floor — not flagged
        self.assertIsNone(
            lint.evaluate_payload(_bash_payload("sleep 60 && tail -20 /tmp/foo.out"))
        )

    def test_sleep_cadence_above_floor_allowed(self) -> None:
        self.assertIsNone(
            lint.evaluate_payload(_bash_payload("sleep 120 && tail -20 /tmp/foo.out"))
        )

    def test_peek_after_completion_allowed(self) -> None:
        # The client saw the exit sentinel (or a stale capture): a repeated
        # peek is post-completion inspection, not polling.
        for state in (FINISHED, STALE):
            with (
                self.subTest(state=state),
                mock.patch.object(lint, "_db_available", return_value=True),
                mock.patch.object(
                    lint, "_recent_bash_commands", return_value=_PRIOR_PEEK
                ),
            ):
                self.assertIsNone(
                    lint.evaluate_payload(
                        _bash_payload(
                            "tail -80 /tmp/foo.out",
                            captures={"/tmp/foo.out": state},
                        )
                    )
                )

    def test_peek_without_client_fact_allowed(self) -> None:
        # No capture fact: no roots, so nothing counts as a capture peek.
        payload = _bash_payload("tail -80 /tmp/foo.out", roots=())
        with (
            mock.patch.object(lint, "_db_available", return_value=True),
            mock.patch.object(lint, "_recent_bash_commands", return_value=_PRIOR_PEEK),
        ):
            self.assertIsNone(lint.evaluate_payload(payload))

    def test_first_peek_while_running_allowed(self) -> None:
        with (
            mock.patch.object(lint, "_db_available", return_value=True),
            mock.patch.object(lint, "_recent_bash_commands", return_value=[]),
        ):
            self.assertIsNone(
                lint.evaluate_payload(
                    _bash_payload("tail -80 /tmp/foo.out", captures=LIVE)
                )
            )

    def test_second_peek_while_running_flagged(self) -> None:
        recent = [
            ("turn-0", "2026-04-24T12:00:00", "tail -80 /tmp/foo.out"),
        ]
        with (
            mock.patch.object(lint, "_db_available", return_value=True),
            mock.patch.object(lint, "_recent_bash_commands", return_value=recent),
        ):
            result = lint.evaluate_payload(
                _bash_payload("tail -80 /tmp/foo.out", turn_id="turn-1", captures=LIVE)
            )
        self.assertIsNotNone(result)
        assert result is not None
        verdict, reason, ctx = result
        self.assertEqual(verdict, "warn")
        self.assertIn("/tmp/foo.out", reason)
        self.assertEqual(ctx.get("capture_file"), "/tmp/foo.out")

    def test_repeated_peeks_on_different_files_not_flagged(self) -> None:
        # Two peeks, different capture files — the guard is scoped to one capture.
        recent = [
            ("turn-0", "2026-04-24T12:00:00", "tail -80 /tmp/other.out"),
        ]
        with (
            mock.patch.object(lint, "_db_available", return_value=True),
            mock.patch.object(lint, "_recent_bash_commands", return_value=recent),
        ):
            self.assertIsNone(
                lint.evaluate_payload(
                    _bash_payload(
                        "tail -80 /tmp/foo.out", turn_id="turn-1", captures=LIVE
                    )
                )
            )

    def test_peek_outside_5_turn_window_not_flagged(self) -> None:
        # Prior peek at turn-0, current turn far later. The window is 5 turns
        # of intervening other Bash activity.
        recent = [
            ("turn-6", "2026-04-24T12:05:00", "git status"),
            ("turn-5", "2026-04-24T12:04:00", "ls"),
            ("turn-4", "2026-04-24T12:03:00", "pwd"),
            ("turn-3", "2026-04-24T12:02:00", "git diff"),
            ("turn-2", "2026-04-24T12:01:30", "git log"),
            ("turn-1", "2026-04-24T12:01:00", "git branch"),
            ("turn-0", "2026-04-24T12:00:00", "tail -80 /tmp/foo.out"),
        ]
        with (
            mock.patch.object(lint, "_db_available", return_value=True),
            mock.patch.object(lint, "_recent_bash_commands", return_value=recent),
        ):
            # The oldest peek at turn-0 is beyond the 5-turn window — should pass.
            self.assertIsNone(
                lint.evaluate_payload(
                    _bash_payload(
                        "tail -80 /tmp/foo.out", turn_id="turn-7", captures=LIVE
                    )
                )
            )

    def test_deny_mode_yields_deny_verdict(self) -> None:
        recent = [
            ("turn-0", "2026-04-24T12:00:00", "tail -80 /tmp/foo.out"),
        ]
        with (
            mock.patch.object(lint, "_read_lint_mode", return_value="deny"),
            mock.patch.object(lint, "_db_available", return_value=True),
            mock.patch.object(lint, "_recent_bash_commands", return_value=recent),
        ):
            result = lint.evaluate_payload(
                _bash_payload("tail -80 /tmp/foo.out", turn_id="turn-1", captures=LIVE)
            )
        self.assertIsNotNone(result)
        assert result is not None
        verdict, _reason, _ctx = result
        self.assertEqual(verdict, "deny")

    def test_progress_peek_description_with_active_bg_allowed(self) -> None:
        # Description text alone no longer blocks unrelated Bash calls.
        recent_with_bg = [
            ("turn-0", "2026-04-24T12:00:00", "sh test.sh > /tmp/foo.out 2>&1"),
        ]
        with (
            mock.patch.object(lint, "_db_available", return_value=True),
            mock.patch.object(
                lint, "_recent_bash_commands", return_value=recent_with_bg
            ),
        ):
            self.assertIsNone(
                lint.evaluate_payload(
                    _bash_payload(
                        "ls /tmp",
                        description="Progress peek",
                        turn_id="turn-1",
                    )
                )
            )

    def test_filler_with_watcher_capture_active_bg_allowed(self) -> None:
        recent_with_bg = [
            (
                "turn-0",
                "2026-04-24T12:00:00",
                "python3 -m yoke_core.tools.watch_pytest "
                "--raw-capture /tmp/raw.log "
                "--progress-capture /tmp/progress.log -- runtime/api/",
            ),
        ]
        with (
            mock.patch.object(lint, "_db_available", return_value=True),
            mock.patch.object(
                lint, "_recent_bash_commands", return_value=recent_with_bg
            ),
        ):
            self.assertIsNone(
                lint.evaluate_payload(_bash_payload("echo wait", turn_id="turn-1"))
            )

    def test_schedule_wakeup_with_active_bg_allowed(self) -> None:
        recent_with_bg = [
            ("turn-0", "2026-04-24T12:00:00", "sh test.sh > /tmp/foo.out 2>&1"),
        ]
        with (
            mock.patch.object(lint, "_db_available", return_value=True),
            mock.patch.object(
                lint, "_recent_bash_commands", return_value=recent_with_bg
            ),
        ):
            self.assertIsNone(
                lint.evaluate_payload(
                    _non_bash_payload("ScheduleWakeup", turn_id="turn-1")
                )
            )

    def test_task_output_with_active_bg_allowed(self) -> None:
        recent_with_bg = [
            ("turn-0", "2026-04-24T12:00:00", "sh test.sh > /tmp/foo.out 2>&1"),
        ]
        with (
            mock.patch.object(lint, "_db_available", return_value=True),
            mock.patch.object(
                lint, "_recent_bash_commands", return_value=recent_with_bg
            ),
        ):
            self.assertIsNone(
                lint.evaluate_payload(
                    _non_bash_payload(
                        "TaskOutput",
                        tool_input={"task_id": "bg-123"},
                        turn_id="turn-1",
                    )
                )
            )

    def test_schedule_wakeup_without_active_bg_allowed(self) -> None:
        self.assertIsNone(lint.evaluate_payload(_non_bash_payload("ScheduleWakeup")))

    def test_task_output_without_active_bg_allowed(self) -> None:
        self.assertIsNone(
            lint.evaluate_payload(
                _non_bash_payload(
                    "TaskOutput",
                    tool_input={"task_id": "bg-123"},
                )
            )
        )

    def test_unrelated_tool_not_flagged(self) -> None:
        self.assertIsNone(
            lint.evaluate_payload(
                _non_bash_payload("Grep", tool_input={"pattern": "x"})
            )
        )

    def test_db_read_with_check_progress_description_not_flagged(self) -> None:
        # Regression: a DB query described as "Check progress notes for task N"
        # must not be denied by description alone.
        recent_with_bg = [
            ("turn-0", "2026-04-24T12:00:00", "sh test.sh > /tmp/foo.out 2>&1"),
        ]
        with (
            mock.patch.object(lint, "_db_available", return_value=True),
            mock.patch.object(
                lint, "_recent_bash_commands", return_value=recent_with_bg
            ),
        ):
            self.assertIsNone(
                lint.evaluate_payload(
                    _bash_payload(
                        "python3 -m yoke_core.cli.db_router query "
                        '"SELECT id, body FROM epic_progress_notes"',
                        description="Check progress notes for task 006",
                        turn_id="turn-1",
                    )
                )
            )
