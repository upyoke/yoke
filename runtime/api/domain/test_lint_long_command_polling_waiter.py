"""Coverage for ``lint_long_command_polling_waiter.evaluate_bg_waiter``.

The waiter rule fires on ``Bash(run_in_background=true)`` whose body
matches a waiter shape (tail -f, sleep && peek, while-sentinel, or
watch_tail) AND whose target path matches an existing in-session
signal (a kickoff capture or an armed Monitor capture). Without a
matching prior signal, the waiter shape is allowed.
"""

from __future__ import annotations

import unittest
from unittest import mock

from yoke_core.domain import lint_long_command_polling_waiter as waiter
from yoke_core.domain.lint_long_command_polling_constants import (
    BG_WAITER_SUPPRESSION_TOKEN,
)


CAPTURE = "/tmp/yoke-pytest.body-budget.raw.log"
SENTINEL = "/tmp/yoke-cmd.done.sentinel"


def _bg_payload(
    command: str,
    *,
    session_id: str = "sess-test",
    tool_use_id: str = "tu-current",
    run_in_background: bool = True,
) -> dict:
    return {
        "tool_name": "Bash",
        "tool_input": {
            "command": command,
            "description": "",
            "run_in_background": run_in_background,
        },
        "session_id": session_id,
        "tool_use_id": tool_use_id,
        "turn_id": "turn-1",
    }


class TestExtractWaiterTarget(unittest.TestCase):
    """Pure-regex shape detection for the four waiter shapes."""

    def test_tail_f_shape(self) -> None:
        shape, target = waiter._extract_waiter_target(f"tail -f {CAPTURE}")
        self.assertEqual(shape, "tail-f")
        self.assertEqual(target, CAPTURE)

    def test_tail_capital_f_shape(self) -> None:
        shape, target = waiter._extract_waiter_target(f"tail -F {CAPTURE}")
        self.assertEqual(shape, "tail-f")
        self.assertEqual(target, CAPTURE)

    def test_sleep_then_peek_shape(self) -> None:
        shape, target = waiter._extract_waiter_target(
            f"sleep 30 && tail -200 {CAPTURE}"
        )
        self.assertEqual(shape, "sleep-then-peek")
        self.assertEqual(target, CAPTURE)

    def test_sleep_then_grep_shape(self) -> None:
        shape, target = waiter._extract_waiter_target(
            f"sleep 30 && grep -E pat {CAPTURE}"
        )
        self.assertEqual(shape, "sleep-then-peek")
        self.assertEqual(target, CAPTURE)

    def test_watch_tail_shape(self) -> None:
        shape, target = waiter._extract_waiter_target(
            f"python3 -m yoke_core.tools.watch_tail {CAPTURE}"
        )
        self.assertEqual(shape, "watch-tail")
        self.assertEqual(target, CAPTURE)

    def test_while_sentinel_shape(self) -> None:
        shape, target = waiter._extract_waiter_target(
            f"while [ ! -f {SENTINEL} ]; do sleep 5; done"
        )
        self.assertEqual(shape, "while-sentinel")
        self.assertEqual(target, SENTINEL)

    def test_substantive_command_no_match(self) -> None:
        shape, target = waiter._extract_waiter_target(
            "python3 -m pytest runtime/api/"
        )
        self.assertIsNone(shape)
        self.assertIsNone(target)


class TestEvaluateBgWaiter(unittest.TestCase):
    def setUp(self) -> None:
        self._mode_patch = mock.patch.object(
            waiter, "_read_lint_mode", return_value="deny"
        )
        self._mode_patch.start()
        self.addCleanup(self._mode_patch.stop)

    def _existing_captures_patch(self, captures: set[str]):
        return mock.patch.object(
            waiter, "_existing_capture_files", return_value=captures
        )

    def test_foreground_bash_not_flagged(self) -> None:
        # Without run_in_background=true the rule does not apply.
        with self._existing_captures_patch({CAPTURE}):
            self.assertIsNone(
                waiter.evaluate_bg_waiter(
                    _bg_payload(
                        f"tail -f {CAPTURE}", run_in_background=False,
                    )
                )
            )

    def test_no_existing_capture_match_allows(self) -> None:
        # Bg waiter shape against a path that is not a known in-session
        # capture: not an anti-pattern (might be a legitimate first
        # background tail).
        with self._existing_captures_patch(set()):
            self.assertIsNone(
                waiter.evaluate_bg_waiter(
                    _bg_payload(f"tail -f {CAPTURE}")
                )
            )

    def test_tail_f_against_existing_capture_denies(self) -> None:
        # AC-8.
        with self._existing_captures_patch({CAPTURE}):
            result = waiter.evaluate_bg_waiter(
                _bg_payload(f"tail -f {CAPTURE}")
            )
        self.assertIsNotNone(result)
        assert result is not None
        verdict, reason, ctx = result
        self.assertEqual(verdict, "deny")
        self.assertEqual(ctx.get("waiter_shape"), "tail-f")
        self.assertIn(CAPTURE, reason)

    def test_sleep_then_tail_against_existing_capture_denies(self) -> None:
        # AC-7.
        with self._existing_captures_patch({CAPTURE}):
            result = waiter.evaluate_bg_waiter(
                _bg_payload(f"sleep 30 && tail -200 {CAPTURE}")
            )
        self.assertIsNotNone(result)
        assert result is not None
        verdict, _reason, ctx = result
        self.assertEqual(verdict, "deny")
        self.assertEqual(ctx.get("waiter_shape"), "sleep-then-peek")

    def test_while_sentinel_against_existing_capture_denies(self) -> None:
        # AC-9.
        with self._existing_captures_patch({SENTINEL}):
            result = waiter.evaluate_bg_waiter(
                _bg_payload(
                    f"while [ ! -f {SENTINEL} ]; do sleep 5; done",
                )
            )
        self.assertIsNotNone(result)
        assert result is not None
        verdict, _reason, ctx = result
        self.assertEqual(verdict, "deny")
        self.assertEqual(ctx.get("waiter_shape"), "while-sentinel")

    def test_watch_tail_against_existing_capture_denies(self) -> None:
        # AC-10.
        with self._existing_captures_patch({CAPTURE}):
            result = waiter.evaluate_bg_waiter(
                _bg_payload(
                    f"python3 -m yoke_core.tools.watch_tail {CAPTURE}",
                )
            )
        self.assertIsNotNone(result)
        assert result is not None
        verdict, _reason, ctx = result
        self.assertEqual(verdict, "deny")
        self.assertEqual(ctx.get("waiter_shape"), "watch-tail")

    def test_suppression_token_audit_only(self) -> None:
        # Token is recorded but does NOT unblock.
        with self._existing_captures_patch({CAPTURE}):
            result = waiter.evaluate_bg_waiter(
                _bg_payload(
                    f"tail -f {CAPTURE}  {BG_WAITER_SUPPRESSION_TOKEN}",
                )
            )
        self.assertIsNotNone(result)
        assert result is not None
        verdict, _reason, ctx = result
        self.assertEqual(verdict, "deny")
        self.assertEqual(ctx.get("outcome"), "suppression_attempted")

    def test_warn_mode_records_without_blocking(self) -> None:
        # Warn-mode emits the verdict but does not block.
        with mock.patch.object(waiter, "_read_lint_mode", return_value="warn"), \
             self._existing_captures_patch({CAPTURE}):
            result = waiter.evaluate_bg_waiter(
                _bg_payload(f"tail -f {CAPTURE}")
            )
        self.assertIsNotNone(result)
        assert result is not None
        verdict, _reason, _ctx = result
        self.assertEqual(verdict, "warn")

    def test_non_bash_tool_skipped(self) -> None:
        payload = _bg_payload(f"tail -f {CAPTURE}")
        payload["tool_name"] = "Read"
        with self._existing_captures_patch({CAPTURE}):
            self.assertIsNone(waiter.evaluate_bg_waiter(payload))


if __name__ == "__main__":
    unittest.main()
