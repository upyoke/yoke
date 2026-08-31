"""Typed ``evaluate`` entry for the PostToolUse DB-error hook."""

from __future__ import annotations

from yoke_core.domain.db_error_hook import evaluate
from yoke_core.hooks.types import HookContext, Next, Outcome


def _context(payload: dict) -> HookContext:
    return HookContext(
        event_name="PostToolUse",
        executor_family="cursor",
        executor_surface="cursor-cli",
        payload=payload,
        tool_name="Bash",
        session_id="sess-db",
    )


def test_evaluate_returns_additional_context_on_query_failure() -> None:
    decision = evaluate(
        _context(
            {
                "tool_input": {"command": "sqlite3 test.db 'SELECT 1'"},
                "tool_response": {"content": "Exit code 1\nError: no such table"},
            }
        )
    )
    assert decision.outcome is Outcome.NOOP
    assert decision.next is Next.CONTINUE
    advisory = decision.audit_fields.get("additionalContext") or ""
    assert "HARD STOP" in advisory
    assert "exit code 1" in advisory


def test_evaluate_clean_output_is_plain_noop() -> None:
    decision = evaluate(
        _context(
            {
                "tool_input": {"command": "echo hello"},
                "tool_response": {"content": "hello"},
            }
        )
    )
    assert decision.outcome is Outcome.NOOP
    assert decision.audit_fields.get("additionalContext") in {None, ""}


def test_evaluate_empty_payload_is_noop() -> None:
    decision = evaluate(_context({}))
    assert decision.outcome is Outcome.NOOP
    assert not decision.audit_fields.get("additionalContext")
