"""Headless Claude watcher Bash must carry the documented timeout."""

from __future__ import annotations

from yoke_core.hooks.decision_render import render_codex_decision

import json
import unittest
from unittest import mock

from yoke_contracts.hook_runner.client_facts import HEADLESS_LAUNCH_KEY, client_fact
from yoke_contracts.session_control.resume import RESUME_ATTEMPT_ENV
from yoke_contracts.watch_cli_forms import IN_TURN_WATCHER_TIMEOUT_MS
from yoke_core.domain import lint_headless_watcher_timeout as lint
from yoke_core.hooks.guard_denial_record import guard_audit_outcome
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
    family: str = "claude",
    headless=True,
):
    return lint.evaluate_payload(
        _payload(command, timeout=timeout, headless=headless),
        executor_family=family,
    )


class TestScope(unittest.TestCase):
    def test_omitted_timeout_is_denied(self):
        verdict = _eval()
        assert verdict is not None
        reason, outcome = verdict
        self.assertEqual(outcome, "denied")
        self.assertIn(f"timeout: {IN_TURN_WATCHER_TIMEOUT_MS}", reason)
        self.assertIn("not a blanket Bash rule", reason)
        self.assertIn("BASH_DEFAULT_TIMEOUT_MS=3600000 before Claude", reason)
        self.assertIn("run_in_background: true with timeout: 3600000", reason)
        self.assertIn("subagents must use foreground Bash", reason)
        self.assertIn("Exporting it inside Bash is too late", reason)
        self.assertNotIn("continue the same backgrounded call until it exits", reason)

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

    def test_print_only_merge_pair_is_clean(self):
        self.assertIsNone(
            _eval(
                "yoke watch merge --print-streaming-pair merge-item -- YOK-4395 --wait"
            )
        )

    def test_print_only_pytest_pair_is_clean(self):
        self.assertIsNone(
            _eval(
                "yoke watch pytest --print-streaming-pair --local -- "
                "runtime/api/domain/test_x.py"
            )
        )

    def test_print_flag_after_separator_still_needs_the_timeout(self):
        self.assertIsNotNone(_eval("yoke watch pytest -- --print-streaming-pair"))

    def test_print_flag_on_another_segment_still_needs_the_timeout(self):
        command = (
            "yoke watch pytest --print-streaming-pair; "
            "yoke watch pytest --impacted main --bounded"
        )
        self.assertIsNotNone(_eval(command))

    def test_non_bash_is_clean(self):
        payload = _payload()
        payload["tool_name"] = "Read"
        decision = lint.evaluate(lint._build_context_from_payload(payload))
        self.assertIs(decision.outcome, Outcome.NOOP)


class TestDecision(unittest.TestCase):
    def test_suppression_does_not_unblock(self):
        verdict = _eval(f"{WATCH} {lint.SUPPRESSION_TOKEN}")
        assert verdict is not None
        self.assertEqual(verdict[1], "suppression_attempted")

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
        self.assertEqual(guard_audit_outcome(decision), "denied")
        envelope = json.loads(render_codex_decision([decision], "PreToolUse")[0])
        reason = envelope["hookSpecificOutput"]["permissionDecisionReason"]
        self.assertIn(str(IN_TURN_WATCHER_TIMEOUT_MS), reason)
