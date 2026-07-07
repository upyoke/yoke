"""Regression: command-substitution pointer-file reads are not polling.

Field-note 12214: ``OUT=$(cat /tmp/infra-render-dir.txt); cd $OUT/infra
&& python3 -m venv venv`` was denied as a manual progress peek. The /tmp
file is a one-line path-pointer note (a mktemp dir name persisted across
Bash subshells), not the capture of any running command; re-reading it
in each subshell preamble is content consumption, not polling.

The carve-out pairs two signals: the peek-verb read is enclosed in a
``$(...)`` command substitution (its bytes feed the command, not the
transcript) AND no recent session command registered the file as a
capture (redirect target or watcher ``--raw-capture`` /
``--progress-capture`` arg). A substitution read of a REGISTERED capture
stays classified — ``OUT=$(tail -5 /tmp/run.out); echo $OUT`` against a
live kickoff's capture is still polling.
"""

from __future__ import annotations

import unittest
from unittest import mock

from yoke_core.domain import lint_long_command_polling_evaluate as lint
from yoke_core.domain.lint_long_command_polling_extract import (
    _peek_read_in_command_substitution,
)
from yoke_core.domain.lint_long_command_polling_test_helpers import (
    _bash_payload,
)

_POINTER_READ = (
    "OUT=$(cat /tmp/infra-render-dir.txt); "
    "cd $OUT/infra && python3 -m venv venv"
)


class TestSubstitutionEnclosure(unittest.TestCase):
    def test_pointer_read_is_enclosed(self) -> None:
        self.assertTrue(_peek_read_in_command_substitution(_POINTER_READ))

    def test_bare_peek_is_not_enclosed(self) -> None:
        self.assertFalse(
            _peek_read_in_command_substitution("tail -80 /tmp/foo.out")
        )

    def test_closed_substitution_before_bare_peek_not_enclosed(self) -> None:
        self.assertFalse(
            _peek_read_in_command_substitution(
                "V=$(date +%s); tail -80 /tmp/foo.out"
            )
        )

    def test_non_peek_command_not_enclosed(self) -> None:
        self.assertFalse(_peek_read_in_command_substitution("git status"))


class TestCaptureRegistration(unittest.TestCase):
    def test_redirect_kickoff_registers_capture(self) -> None:
        recent = [
            ("tu-0", "2026-06-10T12:00:00", "sh test.sh > /tmp/run.out 2>&1"),
        ]
        self.assertTrue(
            lint._capture_registered_in_session(recent, "/tmp/run.out")
        )

    def test_watcher_arg_registers_capture(self) -> None:
        recent = [
            (
                "tu-0",
                "2026-06-10T12:00:00",
                "python3 -m yoke_core.tools.watch_pytest "
                "--raw-capture /tmp/raw.log -- runtime/api/test_x.py",
            ),
        ]
        self.assertTrue(
            lint._capture_registered_in_session(recent, "/tmp/raw.log")
        )

    def test_plain_reads_do_not_register(self) -> None:
        recent = [("tu-0", "2026-06-10T12:00:00", _POINTER_READ)]
        self.assertFalse(
            lint._capture_registered_in_session(
                recent, "/tmp/infra-render-dir.txt"
            )
        )


class TestPointerReadVerdict(unittest.TestCase):
    def setUp(self) -> None:
        patch = mock.patch.object(lint, "_read_lint_mode", return_value="deny")
        patch.start()
        self.addCleanup(patch.stop)

    def test_exact_denied_shape_from_field_note_allowed(self) -> None:
        # Freshly written pointer (mtime says "still running") + a prior
        # subshell read of the same pointer — the exact state that
        # produced the false deny.
        recent = [
            (
                "tu-0",
                "2026-06-10T12:00:00",
                "OUT=$(cat /tmp/infra-render-dir.txt); ls $OUT",
            ),
        ]
        with mock.patch.object(
                lint, "_owning_command_still_running", return_value=True
             ), \
             mock.patch.object(lint, "_db_available", return_value=True), \
             mock.patch.object(
                lint, "_recent_bash_commands", return_value=recent
             ):
            self.assertIsNone(
                lint.evaluate_payload(
                    _bash_payload(_POINTER_READ, tool_use_id="tu-1")
                )
            )

    def test_substitution_read_of_registered_capture_still_flagged(self) -> None:
        # True-positive guard: the same substitution shape against a
        # capture the session kicked off stays a polling peek.
        recent = [
            (
                "tu-1",
                "2026-06-10T12:00:30",
                "OUT=$(tail -5 /tmp/run.out); echo $OUT",
            ),
            ("tu-0", "2026-06-10T12:00:00", "sh test.sh > /tmp/run.out 2>&1"),
        ]
        with mock.patch.object(
                lint, "_owning_command_still_running", return_value=True
             ), \
             mock.patch.object(lint, "_db_available", return_value=True), \
             mock.patch.object(
                lint, "_recent_bash_commands", return_value=recent
             ):
            result = lint.evaluate_payload(
                _bash_payload(
                    "OUT=$(tail -5 /tmp/run.out); echo $OUT",
                    tool_use_id="tu-2",
                )
            )
        self.assertIsNotNone(result)
        assert result is not None
        verdict, reason, ctx = result
        self.assertEqual(verdict, "deny")
        self.assertIn("/tmp/run.out", reason)
        self.assertEqual(ctx.get("capture_file"), "/tmp/run.out")

    def test_bare_repeated_peek_still_flagged(self) -> None:
        # The carve-out never touches the bare-peek path.
        recent = [
            ("tu-0", "2026-06-10T12:00:00", "tail -80 /tmp/foo.out"),
        ]
        with mock.patch.object(
                lint, "_owning_command_still_running", return_value=True
             ), \
             mock.patch.object(lint, "_db_available", return_value=True), \
             mock.patch.object(
                lint, "_recent_bash_commands", return_value=recent
             ):
            result = lint.evaluate_payload(
                _bash_payload("tail -80 /tmp/foo.out", tool_use_id="tu-1")
            )
        self.assertIsNotNone(result)


if __name__ == "__main__":
    unittest.main()
