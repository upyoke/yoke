"""Headless Claude watcher Bash must carry the documented timeout."""

from __future__ import annotations

import json
import unittest
from unittest import mock

from yoke_contracts.hook_runner.client_facts import HEADLESS_LAUNCH_KEY, client_fact
from yoke_contracts.session_control.resume import RESUME_ATTEMPT_ENV
from yoke_contracts.watch_cli_forms import IN_TURN_WATCHER_TIMEOUT_MS
from yoke_core.domain import lint_headless_watcher_timeout as lint
from yoke_core.hooks.types import HookContext, Next, Outcome
from yoke_harness.session_launch_handoff import LAUNCH_CONTEXT_ENV

WATCH = "yoke watch pytest --impacted main --bounded"
HEADLESS_ENV = {LAUNCH_CONTEXT_ENV: "launch-ctx", RESUME_ATTEMPT_ENV: "resume-1"}


def _payload(command: str = WATCH, timeout=None, *, headless=True) -> dict:
    tool_input: dict = {"command": command}
    if timeout is not None:
        tool_input["timeout"] = timeout
    facts = client_fact(HEADLESS_LAUNCH_KEY, headless) if headless is not None else {}
    return {
        **facts,
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
    headless=True,
):
    with mock.patch.object(lint, "_read_mode", return_value=mode):
        return lint.evaluate_payload(
            _payload(command, timeout=timeout, headless=headless),
            executor_family=family,
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
        self.assertIsNone(_eval(headless=False))

    def test_absent_fact_is_interactive(self):
        self.assertIsNone(_eval(headless=None))

    def test_malformed_fact_is_interactive(self):
        self.assertIsNone(_eval(headless="yes"))

    def test_evaluating_process_environment_is_not_read(self):
        with mock.patch.dict("os.environ", HEADLESS_ENV, clear=False):
            self.assertIsNone(_eval(headless=None))

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
            self.assertIsNone(lint.evaluate_payload(payload, executor_family="claude"))


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

    def _decision(self, *, remote: bool = False, headless=True):
        return lint.evaluate(
            HookContext(
                event_name="PreToolUse",
                executor_family="claude",
                executor_surface="cli",
                payload=_payload(headless=headless),
                tool_name="Bash",
                remote=remote,
            )
        )

    def test_verdict_is_the_same_locally_and_remotely(self):
        for headless, outcome in ((True, Outcome.DENY), (False, Outcome.NOOP)):
            local = self._decision(remote=False, headless=headless)
            remote = self._decision(remote=True, headless=headless)
            self.assertEqual(local.outcome, outcome)
            self.assertEqual(remote.outcome, outcome)
            self.assertEqual(local.message, remote.message)

    def test_deny_envelope_names_repair(self):
        decision = self._decision()
        self.assertEqual(decision.outcome, Outcome.DENY)
        self.assertTrue(decision.block)
        self.assertEqual(decision.next, Next.STOP)
        envelope = json.loads(decision.message or "{}")
        reason = envelope["hookSpecificOutput"]["permissionDecisionReason"]
        self.assertIn(str(IN_TURN_WATCHER_TIMEOUT_MS), reason)
