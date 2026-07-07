"""Unit tests for :mod:`yoke_core.domain.lint_subagent_background`."""

from __future__ import annotations

import json
import os
import sys
import unittest
from contextlib import redirect_stdout
from io import StringIO
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", ".."))

from yoke_core.domain import lint_subagent_background as lint
from runtime.harness.hook_runner.types import HookContext, Outcome


def _payload(tool_name, *, command=None, run_in_background=None, reason=None,
             session_id="sess-1"):
    tool_input = {}
    if command is not None:
        tool_input["command"] = command
    if run_in_background is not None:
        tool_input["run_in_background"] = run_in_background
    if reason is not None:
        tool_input["reason"] = reason
    return {
        "tool_name": tool_name,
        "tool_input": tool_input,
        "session_id": session_id,
    }


def _context(payload):
    return HookContext(
        event_name="PreToolUse",
        executor_family="claude",
        executor_surface="claude",
        payload=payload,
        tool_name=payload.get("tool_name"),
        command_body=(payload.get("tool_input") or {}).get("command"),
        cwd="/tmp",
        session_id=payload.get("session_id"),
        item_id=None,
        now=None,
    )


class _AuditEmitter:
    """Stub for ``emit_denial_event`` that records calls."""

    def __init__(self):
        self.calls = []

    def __call__(self, **kwargs):
        self.calls.append(kwargs)


class TestMainSessionFailsOpen(unittest.TestCase):
    def test_no_signal_no_op(self):
        # No YOKE_HOOK_AGENT_TYPE env, no --agent-type, no payload
        # agent_type: the rule must not fire. Main-session
        # background patterns are valid.
        os.environ.pop(lint.AGENT_TYPE_ENV_VAR, None)
        verdict = lint.evaluate_payload(
            _payload("Bash", command="long-running &", run_in_background=True),
        )
        self.assertIsNone(verdict)

    def test_monitor_main_session_no_op(self):
        os.environ.pop(lint.AGENT_TYPE_ENV_VAR, None)
        verdict = lint.evaluate_payload(_payload("Monitor"))
        self.assertIsNone(verdict)


class TestSubagentContextDenies(unittest.TestCase):
    def setUp(self):
        os.environ[lint.AGENT_TYPE_ENV_VAR] = "engineer"
        self.addCleanup(lambda: os.environ.pop(lint.AGENT_TYPE_ENV_VAR, None))
        self._emit_patch = patch(
            "runtime.harness.hook_runner.telemetry.emit_denial_event",
        )
        self.emit_stub = self._emit_patch.start()
        self.addCleanup(self._emit_patch.stop)
        self._mode_patch = patch.object(lint, "_read_lint_mode", return_value="deny")
        self._mode_patch.start()
        self.addCleanup(self._mode_patch.stop)

    def test_denies_monitor_in_subagent_context(self):
        # Subagent attempt to use Monitor is denied.
        verdict = lint.evaluate_payload(_payload("Monitor"))
        self.assertIsNotNone(verdict)
        mode, reason, tool_name, outcome = verdict
        self.assertEqual(mode, "deny")
        self.assertEqual(tool_name, "Monitor")
        self.assertIn("Monitor", reason)
        self.assertEqual(outcome, "denied")

    def test_denies_schedule_wakeup(self):
        verdict = lint.evaluate_payload(_payload("ScheduleWakeup"))
        self.assertIsNotNone(verdict)
        _, reason, tool_name, _ = verdict
        self.assertEqual(tool_name, "ScheduleWakeup")
        self.assertIn("ScheduleWakeup", reason)

    def test_denies_bash_run_in_background(self):
        verdict = lint.evaluate_payload(
            _payload("Bash", command="python3 -m foo", run_in_background=True),
        )
        self.assertIsNotNone(verdict)
        _, reason, tool_name, _ = verdict
        self.assertEqual(tool_name, "Bash")
        self.assertIn("run_in_background", reason)

    def test_denies_backgrounded_watcher_wrapper(self):
        # An explicit `&` background of the watcher wrapper is the
        # structural deadlock shape — deny.
        verdict = lint.evaluate_payload(
            _payload(
                "Bash",
                command=(
                    "python3 -m yoke_core.tools.watch_pytest "
                    "-- runtime/api/ &"
                ),
            ),
        )
        self.assertIsNotNone(verdict)
        _, reason, _, _ = verdict
        self.assertIn("watch_pytest", reason)

    def test_allows_foreground_watcher_wrapper(self):
        # AC-11 mirror: foreground watcher use IS the canonical subagent
        # shape — the lint must not deny it.
        verdict = lint.evaluate_payload(
            _payload(
                "Bash",
                command="python3 -m yoke_core.tools.watch_pytest -- runtime/api/",
            ),
        )
        self.assertIsNone(verdict)

    def test_allows_watcher_with_stderr_redirect(self):
        # `2>&1` is fd duplication, not a backgrounding operator — the
        # lint must not confuse the `&` inside `2>&1` with `cmd &`.
        verdict = lint.evaluate_payload(
            _payload(
                "Bash",
                command=(
                    "python3 -m yoke_core.tools.watch_pytest "
                    "-- runtime/api/ 2>&1"
                ),
            ),
        )
        self.assertIsNone(verdict)

    def test_allows_watcher_with_logical_and(self):
        # `&&` is the logical-AND operator — also not a backgrounding `&`.
        verdict = lint.evaluate_payload(
            _payload(
                "Bash",
                command=(
                    "python3 -m yoke_core.tools.watch_pytest "
                    "-- runtime/api/ && echo done"
                ),
            ),
        )
        self.assertIsNone(verdict)

    def test_suppression_token_records_attempt_does_not_unblock(self):
        # The suppression token is honoured as audit evidence only.
        verdict = lint.evaluate_payload(
            _payload(
                "Bash",
                command="python3 -m foo " + lint.SUPPRESSION_TOKEN,
                run_in_background=True,
            ),
        )
        self.assertIsNotNone(verdict)
        _, reason, _, outcome = verdict
        self.assertEqual(outcome, "suppression_attempted")
        self.assertIn(lint.SUPPRESSION_TOKEN, reason)

    def test_cli_agent_type_overrides_env(self):
        # --agent-type CLI flag must work even when env var is empty.
        os.environ.pop(lint.AGENT_TYPE_ENV_VAR, None)
        verdict = lint.evaluate_payload(
            _payload("Monitor"),
            agent_type="tester",
        )
        self.assertIsNotNone(verdict)


class TestWarnMode(unittest.TestCase):
    def setUp(self):
        os.environ[lint.AGENT_TYPE_ENV_VAR] = "engineer"
        self.addCleanup(lambda: os.environ.pop(lint.AGENT_TYPE_ENV_VAR, None))

    def test_warn_mode_does_not_block(self):
        with patch.object(lint, "_read_lint_mode", return_value="warn"):
            ctx = _context(_payload("Monitor"))
            decision = lint.evaluate(ctx)
        self.assertIs(decision.outcome, Outcome.WARN)
        self.assertFalse(decision.block)


class TestTypedEvaluate(unittest.TestCase):
    def setUp(self):
        os.environ[lint.AGENT_TYPE_ENV_VAR] = "engineer"
        self.addCleanup(lambda: os.environ.pop(lint.AGENT_TYPE_ENV_VAR, None))

    def test_deny_decision_carries_deny_envelope(self):
        with patch.object(lint, "_read_lint_mode", return_value="deny"):
            ctx = _context(_payload("Monitor"))
            decision = lint.evaluate(ctx)
        self.assertIs(decision.outcome, Outcome.DENY)
        self.assertTrue(decision.block)
        envelope = json.loads(decision.message)
        self.assertEqual(
            envelope["hookSpecificOutput"]["permissionDecision"], "deny",
        )

    def test_noop_when_main_session(self):
        os.environ.pop(lint.AGENT_TYPE_ENV_VAR, None)
        ctx = _context(_payload("Monitor"))
        decision = lint.evaluate(ctx)
        self.assertIs(decision.outcome, Outcome.NOOP)


class TestCliMain(unittest.TestCase):
    def setUp(self):
        os.environ[lint.AGENT_TYPE_ENV_VAR] = "engineer"
        self.addCleanup(lambda: os.environ.pop(lint.AGENT_TYPE_ENV_VAR, None))

    def test_cli_emits_deny_envelope_on_stdout(self):
        # Patch stdin to feed a Monitor payload, capture stdout, confirm
        # the deny envelope shape.
        payload = _payload("Monitor")
        argv_backup = sys.argv[:]
        sys.argv = ["lint_subagent_background"]
        try:
            with patch("sys.stdin", StringIO(json.dumps(payload))):
                with patch.object(
                    lint, "_read_lint_mode", return_value="deny",
                ):
                    buf = StringIO()
                    with redirect_stdout(buf):
                        rc = lint.main()
        finally:
            sys.argv = argv_backup
        self.assertEqual(rc, 0)
        output = buf.getvalue().strip()
        envelope = json.loads(output)
        self.assertEqual(
            envelope["hookSpecificOutput"]["permissionDecision"], "deny",
        )

    def test_cli_silent_when_main_session(self):
        os.environ.pop(lint.AGENT_TYPE_ENV_VAR, None)
        payload = _payload("Monitor")
        argv_backup = sys.argv[:]
        sys.argv = ["lint_subagent_background"]
        try:
            with patch("sys.stdin", StringIO(json.dumps(payload))):
                buf = StringIO()
                with redirect_stdout(buf):
                    rc = lint.main()
        finally:
            sys.argv = argv_backup
        self.assertEqual(rc, 0)
        self.assertEqual(buf.getvalue(), "")


class TestSubagentAdapterWiring(unittest.TestCase):
    """AC-1 / AC-11 / AC-3 sibling regressions on the rendered adapter files.

    Walks the on-disk Claude adapter files for every Bash-capable subagent
    and asserts every PreToolUse matcher routes through the universal
    runner with the env-wrapped subagent identity. Also asserts PM/PD
    adapters carry zero ``lint_subagent_background`` invocations.
    """

    _BASH_CAPABLE_ROLES = ("engineer", "tester", "architect", "boss", "simulator")
    _NON_BASH_ROLES = ("product-manager", "product-designer")

    def _claude_adapter_path(self, role: str):
        from runtime.api.domain.test_agents_render_workspace_fixtures import (
            resolve_live_repo_root,
        )

        return (
            resolve_live_repo_root()
            / "runtime"
            / "harness"
            / "claude"
            / "agents"
            / f"yoke-{role}.md"
        )

    def test_each_bash_capable_adapter_renders_seven_pretool_runner_entries(self):
        for role in self._BASH_CAPABLE_ROLES:
            adapter_text = self._claude_adapter_path(role).read_text(encoding="utf-8")
            expected_command = (
                f"YOKE_HOOK_AGENT_TYPE={role} "
                f"yoke hook evaluate PreToolUse"
            )
            count = adapter_text.count(expected_command)
            self.assertEqual(
                count,
                7,
                f"yoke-{role}.md: expected 7 hook CLI PreToolUse entries, got {count}",
            )
            # AC-10 disk-side: no --agent-type CLI flag on any PreToolUse runner.
            self.assertNotIn(
                "yoke_core.domain.lint_subagent_background --agent-type",
                adapter_text,
                f"yoke-{role}.md: stale --agent-type CLI flag still present",
            )

    def test_pm_pd_adapters_have_zero_lint_subagent_background_invocations(self):
        for role in self._NON_BASH_ROLES:
            adapter_text = self._claude_adapter_path(role).read_text(encoding="utf-8")
            self.assertNotIn(
                "lint_subagent_background",
                adapter_text,
                f"yoke-{role}.md: non-Bash agent must carry zero lint_subagent_background invocations",
            )


class TestSubagentBackgroundDeployedMode(unittest.TestCase):
    """AC-14: dogfood policy pins ``lint_subagent_background=deny``."""

    def test_dogfood_config_pins_lint_mode_to_deny(self):
        from runtime.api.domain.test_agents_render_workspace_fixtures import (
            resolve_live_repo_root,
        )

        config_path = resolve_live_repo_root() / ".yoke" / "lint-config"
        body = config_path.read_text(encoding="utf-8")
        self.assertIn(
            "lint_subagent_background=deny",
            body,
            ".yoke/lint-config must pin lint_subagent_background=deny",
        )


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
