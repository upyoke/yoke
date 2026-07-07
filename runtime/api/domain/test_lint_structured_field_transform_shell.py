"""Tests for yoke_core.domain.lint_structured_field_transform_shell.

Per the epic the legacy stdin-driven ``run(stdin_data: str)``
shape is gone; tests construct a :class:`HookContext` and assert against
the typed :class:`HookDecision` instead.
"""

from __future__ import annotations

import json
import unittest
from unittest import mock

from yoke_core.domain import lint_structured_field_transform_shell as lint
from runtime.harness.hook_runner.types import Next, Outcome


def _payload(command: str) -> dict:
    return {
        "tool_name": "Bash",
        "tool_input": {"command": command},
        "session_id": "sess-test",
        "tool_use_id": "tu-test",
        "turn_id": "turn-test",
    }


def _record_for(payload: dict) -> "lint.HookContext":
    """Build the HookContext shape the entry-point's CLI helper would build."""
    return lint._build_context_from_payload(payload)


class TestExtractCommand(unittest.TestCase):
    def test_tool_input_command(self) -> None:
        self.assertEqual(
            lint._extract_command({"tool_input": {"command": "items get 1 spec"}}),
            "items get 1 spec",
        )

    def test_camel_case(self) -> None:
        self.assertEqual(
            lint._extract_command({"toolInput": {"command": "echo"}}),
            "echo",
        )

    def test_cmd_fallback(self) -> None:
        self.assertEqual(
            lint._extract_command({"tool_input": {"cmd": "git log"}}),
            "git log",
        )

    def test_empty(self) -> None:
        self.assertEqual(lint._extract_command({}), "")


class TestEvaluateCommandAllows(unittest.TestCase):
    def test_empty_command(self) -> None:
        self.assertIsNone(lint.evaluate_command(""))

    def test_read_only_get(self) -> None:
        cmd = "python3 -m yoke_core.cli.db_router items get 42 spec"
        self.assertIsNone(lint.evaluate_command(cmd))

    def test_read_only_section_get(self) -> None:
        section = "'Progress " "Log'"
        cmd = f"python3 -m yoke_core.cli.db_router sections get 42 {section}"
        self.assertIsNone(lint.evaluate_command(cmd))

    def test_direct_stdin_write(self) -> None:
        cmd = (
            'printf "%s" "intended full content" '
            '| python3 -m yoke_core.cli.db_router items update 42 spec --stdin'
        )
        self.assertIsNone(lint.evaluate_command(cmd))

    def test_heredoc_stdin_write(self) -> None:
        cmd = (
            "cat <<'EOF' | python3 -m yoke_core.cli.db_router items update 42 spec --stdin\n"
            "full intended content\n"
            "EOF\n"
        )
        self.assertIsNone(lint.evaluate_command(cmd))

    def test_body_file_write(self) -> None:
        cmd = (
            "python3 -m yoke_core.cli.db_router items update 42 spec "
            "--body-file /tmp/spec-artifact.md"
        )
        self.assertIsNone(lint.evaluate_command(cmd))

    def test_helper_invocation(self) -> None:
        cmd = (
            "printf '%s' 'extra' | python3 -m yoke_core.domain.item_field_transform "
            "append-addendum --item YOK-42 --field spec --heading 'Refinement Addendum' "
            "--source refine --stdin"
        )
        self.assertIsNone(lint.evaluate_command(cmd))

    def test_get_followed_by_unrelated_pipe(self) -> None:
        # Piping to head/tail/grep is inspection, not transform-back.
        cmd = "python3 -m yoke_core.cli.db_router items get 42 spec | head -20"
        self.assertIsNone(lint.evaluate_command(cmd))

    def test_bypass_token(self) -> None:
        cmd = (
            "python3 -m yoke_core.cli.db_router items get 42 spec > /tmp/old.md "
            "&& python3 transform.py /tmp/old.md > /tmp/new.md "
            "&& cat /tmp/new.md | python3 -m yoke_core.cli.db_router "
            "items update 42 spec --stdin "
            "# lint:no-structured-transform-check"
        )
        self.assertIsNone(lint.evaluate_command(cmd))


class TestEvaluateCommandBlocks(unittest.TestCase):
    def test_redirect_then_stdin_write(self) -> None:
        cmd = (
            "python3 -m yoke_core.cli.db_router items get 42 spec > /tmp/old.md "
            "&& python3 transform.py /tmp/old.md > /tmp/new.md "
            "&& cat /tmp/new.md | python3 -m yoke_core.cli.db_router "
            "items update 42 spec --stdin"
        )
        reason = lint.evaluate_command(cmd)
        self.assertIsNotNone(reason)
        self.assertIn("structured-field transform via shell choreography", reason)
        self.assertIn("item_field_transform", reason)
        # Remediation names section-append for Progress Log appends.
        self.assertIn("section-append", reason)
        self.assertIn("Progress Log", reason)
        # AC-14.3: remediation names the function-call surface.
        self.assertIn("FunctionCallRequest", reason)
        self.assertIn("yoke_function_dispatch", reason)

    def test_sections_get_then_upsert_content_file(self) -> None:
        section = "'Progress " "Log'"
        cmd = (
            f"python3 -m yoke_core.cli.db_router sections get 42 {section} "
            "> /tmp/progress.md && "
            "python3 transform.py /tmp/progress.md > /tmp/progress-new.md && "
            f"python3 -m yoke_core.cli.db_router sections upsert 42 {section} "
            "--content-file /tmp/progress-new.md"
        )
        reason = lint.evaluate_command(cmd)
        self.assertIsNotNone(reason)
        self.assertIn("section-append", reason)
        self.assertIn("sections upsert", reason)

    def test_command_substitution_capture(self) -> None:
        cmd = (
            "_old=$(python3 -m yoke_core.cli.db_router items get 42 spec) && "
            'printf "%s\\n## Addendum\\nbody" "$_old" '
            "| python3 -m yoke_core.cli.db_router items update 42 spec --stdin"
        )
        reason = lint.evaluate_command(cmd)
        self.assertIsNotNone(reason)

    def test_get_pipe_to_python_then_stdin_write(self) -> None:
        cmd = (
            "python3 -m yoke_core.cli.db_router items get 42 spec | "
            "python3 -c 'import sys; print(sys.stdin.read() + \"\\n## X\\n\")' > /tmp/n.md && "
            "python3 -m yoke_core.cli.db_router items update 42 spec --stdin < /tmp/n.md"
        )
        reason = lint.evaluate_command(cmd)
        self.assertIsNotNone(reason)

    def test_get_pipe_to_sed_then_stdin_write(self) -> None:
        cmd = (
            "python3 -m yoke_core.cli.db_router items get 42 technical_plan | "
            "sed 's/foo/bar/' > /tmp/n.md && "
            "cat /tmp/n.md | python3 -m yoke_core.cli.db_router "
            "items update 42 technical_plan --stdin"
        )
        reason = lint.evaluate_command(cmd)
        self.assertIsNotNone(reason)


class TestEvaluate(unittest.TestCase):
    def test_evaluate_blocks_on_match(self) -> None:
        cmd = (
            "items get 42 spec > /tmp/old.md && "
            "items update 42 spec --stdin < /tmp/new.md"
        )
        with mock.patch.object(lint, "_emit_denial"):
            decision = lint.evaluate(_record_for(_payload(cmd)))
        self.assertIs(decision.outcome, Outcome.DENY)
        self.assertTrue(decision.block)
        self.assertIs(decision.next, Next.STOP)
        decoded = json.loads(decision.message)
        self.assertEqual(
            decoded["hookSpecificOutput"]["permissionDecision"], "deny",
        )

    def test_evaluate_allows_safe_command(self) -> None:
        with mock.patch.object(lint, "_emit_denial"):
            decision = lint.evaluate(_record_for(_payload("git status")))
        self.assertIs(decision.outcome, Outcome.NOOP)
        self.assertEqual(decision.message, "")
        self.assertFalse(decision.block)
        self.assertIs(decision.next, Next.CONTINUE)

    def test_evaluate_handles_empty_payload(self) -> None:
        decision = lint.evaluate(_record_for({}))
        self.assertIs(decision.outcome, Outcome.NOOP)
        self.assertFalse(decision.block)

    def test_evaluate_handles_non_dict_payload(self) -> None:
        # Defensive shape: payload defaults to {} when not a dict.
        record = lint.HookContext(
            event_name="PreToolUse", executor_family="claude",
            executor_surface="claude", payload={})
        decision = lint.evaluate(record)
        self.assertIs(decision.outcome, Outcome.NOOP)

    def test_evaluate_audits_bypass_token_still_returns_noop(self) -> None:
        # AC-T3: suppression-token is audit-only; evaluate returns NOOP (the
        # rule does NOT unblock — it audits then declines to deny).
        cmd = (
            "items get 42 spec > /tmp/old.md && "
            "items update 42 spec --stdin < /tmp/new.md "
            "# lint:no-structured-transform-check"
        )
        calls = []
        with mock.patch.object(
            lint,
            "_emit_denial",
            lambda _payload, _reason, *, outcome="denied": calls.append(outcome),
        ):
            decision = lint.evaluate(_record_for(_payload(cmd)))
        # Suppression-token semantics preserved: emits audit-only event, no deny.
        self.assertIs(decision.outcome, Outcome.NOOP)
        self.assertEqual(calls, ["suppression_attempted"])


if __name__ == "__main__":
    unittest.main()
