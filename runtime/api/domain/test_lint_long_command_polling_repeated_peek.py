"""Repeated-peek regression fixture and polling-mode pinning.

Every repeated peek shape from an unblocked-peek audit denies once the
same capture was already peeked while its owning command runs. The
running state comes from the client capture fact on the payload.
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


class TestThirtyPlusPeekRegression(unittest.TestCase):
    """Regression fixture: every repeated peek shape denies now.

    Anonymized from session ``6e2f986d-02f1-449d-8162-a2c8dcec33ef``
    (single pytest backgrounded with ``--raw-capture
    /tmp/yoke-pytest.body-budget.raw.log``). Every shape past the
    first should deny under the widened lint.
    """

    CAPTURE = "/tmp/yoke-pytest.body-budget.raw.log"
    CLAUDE_TASK_OUTPUT = "/private/tmp/claude-501/abcd1234ef56/tasks/b8ly752ok.output"

    REGRESSION_COMMANDS = [
        f'grep -E "passed in|failed in" {CAPTURE}',
        f'grep -E "passed|failed|error in" {CAPTURE}',
        f'grep -c "test" {CAPTURE}',
        f"wc -l {CAPTURE}",
        f'grep -E "passed|failed" {CAPTURE}',
        f"cat {CLAUDE_TASK_OUTPUT}",
        f"ls -la {CAPTURE}",
        f"cat {CLAUDE_TASK_OUTPUT}",
        f'grep -E "passed|failed|error" {CAPTURE}',
        f"tail -10 {CAPTURE}",
        f"tail -5 {CAPTURE}",
        f"wc -l {CAPTURE}",
        f"wc -l {CAPTURE}",
        f"stat {CAPTURE}",
        f"awk '/PASS/{{print}}' {CAPTURE}",
    ]

    def setUp(self) -> None:
        self._mode_patch = mock.patch.object(
            lint, "_read_lint_mode", return_value="deny"
        )
        self._mode_patch.start()
        self.addCleanup(self._mode_patch.stop)

    def test_every_shape_denies_when_same_capture_was_already_peeked(self) -> None:
        with (
            mock.patch.object(lint, "_owning_command_still_running", return_value=True),
            mock.patch.object(lint, "_db_available", return_value=True),
        ):
            for index, command in enumerate(self.REGRESSION_COMMANDS):
                with self.subTest(index=index, command=command):
                    target = _extract_peek_capture_file(command, ROOTS)
                    assert target is not None
                    recent = [
                        (
                            f"tu-prior-{index}",
                            "2026-04-24T12:00:00",
                            f"tail -80 {target}",
                        ),
                    ]
                    with mock.patch.object(
                        lint, "_recent_bash_commands", return_value=recent
                    ):
                        result = lint.evaluate_payload(
                            _bash_payload(command, tool_use_id=f"tu-current-{index}")
                        )
                    self.assertIsNotNone(
                        result, f"shape #{index} {command!r} should deny"
                    )
                    assert result is not None
                    verdict, _reason, _ctx = result
                    self.assertEqual(verdict, "deny")


class TestModePinning(unittest.TestCase):
    """Polling guard mode pin: warn records audit only; deny blocks.

    Warn-mode preserves the historical "audit-only" behaviour; Yoke dogfood
    pins ``deny`` in ``.yoke/lint-config`` (resolved via lint_config).
    """

    def test_warn_mode_returns_warn_verdict(self) -> None:
        recent = [("tu-prior", "2026-04-24T12:00:00", "tail -80 /tmp/foo.out")]
        with (
            mock.patch.object(lint, "_read_lint_mode", return_value="warn"),
            mock.patch.object(lint, "_owning_command_still_running", return_value=True),
            mock.patch.object(lint, "_db_available", return_value=True),
            mock.patch.object(lint, "_recent_bash_commands", return_value=recent),
        ):
            result = lint.evaluate_payload(
                _bash_payload("wc -l /tmp/foo.out", tool_use_id="tu-current")
            )
        self.assertIsNotNone(result)
        assert result is not None
        verdict, _reason, _ctx = result
        self.assertEqual(verdict, "warn")


if __name__ == "__main__":
    unittest.main()
