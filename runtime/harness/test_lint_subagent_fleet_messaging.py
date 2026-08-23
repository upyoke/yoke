"""Subagents cannot mutate Fleet messages through parent identity."""

from __future__ import annotations

import pytest

from yoke_core.domain import lint_subagent_fleet_messaging as lint
from yoke_core.hooks.types import HookContext, Outcome


def _context(command: str, *, payload: dict | None = None) -> HookContext:
    return HookContext(
        event_name="PreToolUse",
        executor_family="claude",
        executor_surface="claude-cli",
        payload=payload or {},
        tool_name="Bash",
        command_body=command,
        session_id="parent",
    )


@pytest.mark.parametrize(
    "command",
    [
        "printf '%s\\n' message | yoke say --session peer --stdin",
        "yoke session-control message send --stdin --session peer",
        "yoke messages acknowledge message-id",
        "yoke messages ack message-id",
        "yoke messages cancel message-id",
        "yoke session-control message cancel message-id",
        "yoke session-control qualification open --project yoke",
    ],
)
def test_subagent_fleet_mutations_are_denied(command: str) -> None:
    decision = lint.evaluate(_context(command, payload={"agent_type": "engineer"}))

    assert decision.outcome is Outcome.DENY
    assert decision.block is True
    assert "receipts shared with their parent read-only" in decision.message
    assert "harness-native parent/subagent channel" in decision.message
    assert "cancel Fleet messages or handle Fleet wake requests" in decision.message


def test_parent_can_mutate_fleet_messages() -> None:
    for command in (
        "printf message | yoke say --session peer --stdin",
        "yoke messages acknowledge message-id",
        "yoke messages cancel message-id",
    ):
        assert lint.evaluate(_context(command)).outcome is Outcome.NOOP


def test_subagent_non_fleet_command_is_unchanged() -> None:
    decision = lint.evaluate(
        _context("yoke sessions list", payload={"subagent_execution": True})
    )
    assert decision.outcome is Outcome.NOOP
