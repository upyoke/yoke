"""Tests for :mod:`yoke_core.domain.hint_posttool_field_note`.

PostToolUse field-note advisory coverage: heuristic precision
(``python3 -m runtime.api.*`` + installed ``yoke``
binary), non-zero exit triggers, zero / non-Yoke / malformed NOOPs,
crash isolation (F-3), and latency budget (NFR-5, <10ms).
"""

from __future__ import annotations

import io
import json
import sys as _sys
import time
import unittest
from contextlib import redirect_stdout
from typing import Any

from yoke_core.domain import hint_posttool_field_note as hook
from yoke_contracts.field_note_text import FOOTER
from runtime.harness.hook_runner.types import HookContext, Next, Outcome

# Placeholder item id used in command-string fixtures. Per AGENTS.md
# "No hardcoded drifting IDs in tests", we synthesize the YOK-N form from
# a numeric constant so future renames re-edit one line, not N.
TEST_ITEM_ID = 42
TEST_ITEM_REF = f"YOK-{TEST_ITEM_ID}"


def _payload(
    *, tool_name: str = "Bash", command: str = "", exit_code: int | None = None,
) -> dict[str, Any]:
    response = f"Exit code {exit_code}" if exit_code is not None else ""
    return {
        "tool_name": tool_name,
        "tool_input": {"command": command},
        "tool_response": {"content": response},
    }


def _ctx(payload: dict[str, Any]) -> HookContext:
    return HookContext(
        event_name="PostToolUse",
        executor_family="claude",
        executor_surface="claude",
        payload=payload,
        tool_name=payload.get("tool_name"),
    )


def _run_main(payload: dict[str, Any]) -> tuple[int, str]:
    prior = _sys.stdin
    _sys.stdin = io.StringIO(json.dumps(payload))
    try:
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = hook.main()
    finally:
        _sys.stdin = prior
    return rc, buf.getvalue()


class TestIsYokeCliCommand(unittest.TestCase):
    """The heuristic is precise — only Yoke CLI surfaces match."""

    def test_TC_python3_m_runtime_api_matches(self) -> None:
        self.assertTrue(hook.is_yoke_cli_command(
            f"python3 -m yoke_core.cli.db_router items get {TEST_ITEM_REF}"
        ))

    def test_TC_python3_m_runtime_api_in_compound_matches(self) -> None:
        self.assertTrue(hook.is_yoke_cli_command(
            "cd /tmp && python3 -m yoke_core.api.service_client backlog-cli list"
        ))

    def test_TC_python3_m_runtime_api_with_pipe_matches(self) -> None:
        self.assertTrue(hook.is_yoke_cli_command(
            "python3 -m yoke_core.cli.db_router events tail | head -5"
        ))

    def test_TC_transitional_python3_m_runtime_api_matches(self) -> None:
        self.assertTrue(hook.is_yoke_cli_command(
            "python3 -m runtime.api.cli.db_router items get YOK-1 status"
        ))

    def test_TC_yoke_binary_matches(self) -> None:
        self.assertTrue(hook.is_yoke_cli_command(
            f"yoke items get {TEST_ITEM_REF}"
        ))

    def test_TC_yoke_binary_with_env_assignment_matches(self) -> None:
        self.assertTrue(hook.is_yoke_cli_command(
            f"YOKE_DB=/tmp/x.db yoke items get {TEST_ITEM_REF}"
        ))

    def test_TC_yoke_binary_in_chain_matches(self) -> None:
        self.assertTrue(hook.is_yoke_cli_command(
            "git -C /repo pull && yoke lifecycle transition YOK-1 --to refined-idea"
        ))

    def test_TC_arbitrary_python3_does_not_match(self) -> None:
        self.assertFalse(hook.is_yoke_cli_command("python3 /tmp/some_script.py"))

    def test_TC_python3_m_other_module_does_not_match(self) -> None:
        self.assertFalse(hook.is_yoke_cli_command("python3 -m pytest runtime/"))
        self.assertFalse(hook.is_yoke_cli_command("python3 -m json.tool /tmp/x.json"))

    def test_TC_python3_m_runtime_harness_does_not_match(self) -> None:
        # Heuristic anchor is `runtime.api.` specifically; `runtime.harness.`
        # is out of scope for the Yoke CLI surface boundary.
        self.assertFalse(hook.is_yoke_cli_command(
            "python3 -m runtime.harness.hook_runner PreToolUse"
        ))

    def test_TC_word_containing_yoke_does_not_match(self) -> None:
        # First token must equal `yoke`, not merely contain the substring.
        self.assertFalse(hook.is_yoke_cli_command("yokereport --json"))
        self.assertFalse(hook.is_yoke_cli_command("/opt/notyoke/bin/x"))

    def test_TC_unrelated_commands_do_not_match(self) -> None:
        for cmd in ("git status", "ls -la /tmp", "", None):
            self.assertFalse(hook.is_yoke_cli_command(cmd))  # type: ignore[arg-type]

    def test_TC_unbalanced_quotes_does_not_crash(self) -> None:
        # shlex.ValueError fallback path must not raise.
        hook.is_yoke_cli_command("yoke items get YOK-1 --field 'unclosed")


class TestParseExitCode(unittest.TestCase):
    def test_TC_dict_content_string(self) -> None:
        self.assertEqual(
            hook.parse_exit_code({"content": "Exit code 1\nstderr"}), 1
        )

    def test_TC_dict_content_list_of_blocks(self) -> None:
        self.assertEqual(
            hook.parse_exit_code({"content": [{"text": "Exit code 7"}]}), 7
        )

    def test_TC_bare_string(self) -> None:
        self.assertEqual(hook.parse_exit_code("Exit code 0\n"), 0)

    def test_TC_unparseable_or_missing_returns_none(self) -> None:
        self.assertIsNone(hook.parse_exit_code({"content": "no marker"}))
        self.assertIsNone(hook.parse_exit_code(None))
        self.assertIsNone(hook.parse_exit_code(12345))


class TestEvaluate(unittest.TestCase):
    def test_TC_nonzero_yoke_cli_emits_advisory(self) -> None:
        # PostToolUse hook fires on non-zero Yoke-CLI exit.
        cmd = f"yoke items get {TEST_ITEM_REF}"
        decision = hook.evaluate(_ctx(_payload(command=cmd, exit_code=1)))
        self.assertEqual(decision.outcome, Outcome.NOOP)
        self.assertEqual(decision.next, Next.CONTINUE)
        advisory = decision.audit_fields["additionalContext"]
        # FOOTER appears verbatim — single source of truth.
        self.assertIn(FOOTER, advisory)
        self.assertIn(cmd, advisory)
        self.assertIn("exit_code=1", advisory)

    def test_TC_nonzero_python3_runtime_api_emits_advisory(self) -> None:
        decision = hook.evaluate(_ctx(_payload(
            command=(
                f"python3 -m yoke_core.cli.db_router items get {TEST_ITEM_REF}"
            ),
            exit_code=2,
        )))
        self.assertIn("additionalContext", decision.audit_fields)
        self.assertIn(FOOTER, decision.audit_fields["additionalContext"])

    def test_TC_zero_exit_does_not_emit(self) -> None:
        decision = hook.evaluate(_ctx(_payload(
            command=f"yoke items get {TEST_ITEM_REF}", exit_code=0,
        )))
        self.assertNotIn("additionalContext", decision.audit_fields)

    def test_TC_nonzero_non_yoke_does_not_emit(self) -> None:
        decision = hook.evaluate(_ctx(_payload(
            command="git status", exit_code=128,
        )))
        self.assertNotIn("additionalContext", decision.audit_fields)

    def test_TC_non_bash_tool_noop(self) -> None:
        decision = hook.evaluate(_ctx(_payload(
            tool_name="Write",
            command=f"yoke items get {TEST_ITEM_REF}",
            exit_code=1,
        )))
        self.assertNotIn("additionalContext", decision.audit_fields)

    def test_TC_missing_exit_code_noop(self) -> None:
        decision = hook.evaluate(_ctx({
            "tool_name": "Bash",
            "tool_input": {"command": f"yoke items get {TEST_ITEM_REF}"},
            "tool_response": {"content": ""},
        }))
        self.assertNotIn("additionalContext", decision.audit_fields)

    def test_TC_missing_or_malformed_tool_input_noop(self) -> None:
        for payload in (
            {"tool_name": "Bash", "tool_response": {"content": "Exit code 1"}},
            {
                "tool_name": "Bash", "tool_input": "not a dict",
                "tool_response": {"content": "Exit code 1"},
            },
        ):
            self.assertEqual(hook.evaluate(_ctx(payload)).outcome, Outcome.NOOP)

    def test_TC_command_truncation_in_advisory(self) -> None:
        # Very long commands are truncated to keep the advisory compact.
        long_cmd = f"yoke items get {TEST_ITEM_REF} " + ("x" * 500)
        decision = hook.evaluate(_ctx(_payload(command=long_cmd, exit_code=1)))
        advisory = decision.audit_fields["additionalContext"]
        self.assertIn("...", advisory)
        head = [
            ln for ln in advisory.splitlines() if ln.startswith("Yoke CLI exited")
        ][0]
        self.assertLessEqual(len(head), 300)


class TestMainCli(unittest.TestCase):
    """CLI shim correctly wraps the typed evaluate path."""

    def test_TC_main_emits_envelope_on_nonzero_yoke(self) -> None:
        rc, out = _run_main(_payload(
            command=f"yoke items get {TEST_ITEM_REF}", exit_code=1,
        ))
        self.assertEqual(rc, 0)
        self.assertTrue(out.strip())
        envelope = json.loads(out)
        self.assertEqual(envelope["hookSpecificOutput"]["hookEventName"], "PostToolUse")
        self.assertIn(FOOTER, envelope["hookSpecificOutput"]["additionalContext"])

    def test_TC_main_noop_on_zero_exit(self) -> None:
        rc, out = _run_main(_payload(
            command=f"yoke items get {TEST_ITEM_REF}", exit_code=0,
        ))
        self.assertEqual(rc, 0)
        self.assertEqual(out, "")

    def test_TC_main_noop_on_non_yoke_command(self) -> None:
        rc, out = _run_main(_payload(command="git status", exit_code=128))
        self.assertEqual(rc, 0)
        self.assertEqual(out, "")

    def test_TC_main_handles_empty_stdin(self) -> None:
        prior = _sys.stdin
        _sys.stdin = io.StringIO("")
        try:
            buf = io.StringIO()
            with redirect_stdout(buf):
                rc = hook.main()
        finally:
            _sys.stdin = prior
        self.assertEqual(rc, 0)
        self.assertEqual(buf.getvalue(), "")

    def test_TC_main_handles_malformed_json(self) -> None:
        prior = _sys.stdin
        _sys.stdin = io.StringIO("{not valid json")
        try:
            buf = io.StringIO()
            with redirect_stdout(buf):
                rc = hook.main()
        finally:
            _sys.stdin = prior
        self.assertEqual(rc, 0)
        self.assertEqual(buf.getvalue(), "")


class TestCrashIsolation(unittest.TestCase):
    """F-3: hook exceptions must not bubble up — fail-open is the contract."""

    def test_TC_evaluate_with_non_dict_payload_does_not_raise(self) -> None:
        ctx = HookContext(
            event_name="PostToolUse",
            executor_family="claude",
            executor_surface="claude",
            payload=None,  # type: ignore[arg-type]
            tool_name="Bash",
        )
        self.assertEqual(hook.evaluate(ctx).outcome, Outcome.NOOP)

    def test_TC_main_swallows_internal_exception(self) -> None:
        prior = _sys.stdin
        _sys.stdin = io.StringIO(json.dumps(_payload(
            command=f"yoke items get {TEST_ITEM_REF}", exit_code=1,
        )))
        original = hook.evaluate
        try:
            hook.evaluate = lambda ctx: (_ for _ in ()).throw(  # type: ignore[assignment]
                RuntimeError("synthetic parse error")
            )
            buf = io.StringIO()
            with redirect_stdout(buf):
                rc = hook.main()
        finally:
            hook.evaluate = original
            _sys.stdin = prior
        self.assertEqual(rc, 0)
        self.assertEqual(buf.getvalue(), "")


class TestLatencyBudget(unittest.TestCase):
    """NFR-5: hook completes <10ms in the happy path (path-string parse only)."""

    def test_TC_hook_latency_under_10ms(self) -> None:
        ctx = _ctx(_payload(
            command=f"yoke items get {TEST_ITEM_REF}", exit_code=1,
        ))
        # Warm-up: pay first-call import / regex compile cost once.
        hook.evaluate(ctx)
        slowest_ms = 0.0
        for _ in range(5):
            start = time.perf_counter()
            hook.evaluate(ctx)
            slowest_ms = max(slowest_ms, (time.perf_counter() - start) * 1000.0)
        self.assertLess(
            slowest_ms, 10.0, f"hook took {slowest_ms:.2f}ms (>10ms cap)"
        )


if __name__ == "__main__":
    unittest.main()
