"""Headless Claude watcher Bash must carry the documented timeout."""

from __future__ import annotations

import json
import unittest
from unittest import mock

from yoke_contracts.session_control.resume import RESUME_ATTEMPT_ENV
from yoke_contracts.watch_cli_forms import IN_TURN_WATCHER_TIMEOUT_MS
from yoke_core.domain import lint_headless_watcher_timeout as lint
from yoke_core.hooks.types import HookContext, Next, Outcome
from yoke_harness.session_launch_handoff import LAUNCH_CONTEXT_ENV

WATCH = "yoke watch pytest --impacted main --bounded"
HEADLESS = {LAUNCH_CONTEXT_ENV: "launch-ctx"}


def _payload(command: str = WATCH, timeout=None) -> dict:
    tool_input: dict = {"command": command}
    if timeout is not None:
        tool_input["timeout"] = timeout
    return {
        "tool_name": "Bash",
        "tool_input": tool_input,
        "session_id": "sess-test",
        "tool_use_id": "tu-test",
        "turn_id": "turn-test",
    }


def _eval(
    command: str = WATCH,
    *,
    timeout=None,
    mode: str = "deny",
    family: str = "claude",
    environ: dict | None = None,
):
    with mock.patch.object(lint, "_read_mode", return_value=mode):
        return lint.evaluate_payload(
            _payload(command, timeout=timeout),
            executor_family=family,
            environ=HEADLESS if environ is None else environ,
        )


class TestScope(unittest.TestCase):
    def test_omitted_timeout_is_denied(self):
        verdict = _eval()
        assert verdict is not None
        mode, reason, outcome = verdict
        self.assertEqual(mode, "deny")
        self.assertEqual(outcome, "denied")
        self.assertIn(f"timeout: {IN_TURN_WATCHER_TIMEOUT_MS}", reason)
        self.assertIn("not a blanket Bash rule", reason)
        self.assertIn("cannot hold after that PostToolUse", reason)

    def test_low_timeout_is_denied(self):
        self.assertIsNotNone(_eval(timeout=120000))

    def test_documented_timeout_is_clean(self):
        self.assertIsNone(_eval(timeout=IN_TURN_WATCHER_TIMEOUT_MS))

    def test_interactive_session_is_clean(self):
        self.assertIsNone(_eval(environ={}))

    def test_resume_marker_is_headless(self):
        self.assertIsNotNone(_eval(environ={RESUME_ATTEMPT_ENV: "resume-1"}))

    def test_cursor_is_clean(self):
        self.assertIsNone(_eval(family="cursor"))

    def test_non_watcher_bash_is_clean(self):
        self.assertIsNone(_eval("yoke items get YOK-1 body"))

    def test_dev_run_watcher_is_in_scope(self):
        self.assertIsNotNone(_eval("yoke dev run -- yoke watch doctor -- --quick"))

    def test_quoted_prose_is_clean(self):
        self.assertIsNone(_eval("echo yoke watch pytest"))

    def test_global_env_flag_before_watch_is_in_scope(self):
        self.assertIsNotNone(_eval("yoke --env prod watch pytest"))

    def test_non_bash_is_clean(self):
        payload = _payload()
        payload["tool_name"] = "Read"
        with mock.patch.object(lint, "_read_mode", return_value="deny"):
            self.assertIsNone(
                lint.evaluate_payload(
                    payload,
                    executor_family="claude",
                    environ=HEADLESS,
                )
            )


class TestModesAndEnvelope(unittest.TestCase):
    def test_warn_mode_is_advisory(self):
        verdict = _eval(mode="warn")
        assert verdict is not None
        mode, reason, outcome = verdict
        self.assertEqual(mode, "warn")
        self.assertEqual(outcome, "warned")
        self.assertIn("would block", reason)

    def test_suppression_does_not_unblock(self):
        verdict = _eval(f"{WATCH} {lint.SUPPRESSION_TOKEN}")
        assert verdict is not None
        self.assertEqual(verdict[2], "suppression_attempted")

    def test_deny_envelope_names_repair(self):
        with mock.patch.dict("os.environ", HEADLESS, clear=False):
            decision = lint.evaluate(
                HookContext(
                    event_name="PreToolUse",
                    executor_family="claude",
                    executor_surface="cli",
                    payload=_payload(),
                    tool_name="Bash",
                )
            )
        self.assertEqual(decision.outcome, Outcome.DENY)
        self.assertTrue(decision.block)
        self.assertEqual(decision.next, Next.STOP)
        envelope = json.loads(decision.message or "{}")
        reason = envelope["hookSpecificOutput"]["permissionDecisionReason"]
        self.assertIn(str(IN_TURN_WATCHER_TIMEOUT_MS), reason)
