"""Typed ``evaluate`` entry for PostToolUse observe telemetry."""

from __future__ import annotations

from unittest import mock

from yoke_core.domain.observe import evaluate
from yoke_core.hooks.types import HookContext, Next, Outcome


def _context(**overrides: object) -> HookContext:
    payload = {
        "tool_name": "Bash",
        "tool_input": {"command": "echo hi"},
        "tool_use_id": "tu-1",
    }
    fields: dict[str, object] = {
        "event_name": "PostToolUse",
        "executor_family": "cursor",
        "executor_surface": "cursor-cli",
        "payload": payload,
        "session_id": "sess-1",
        "cwd": "/tmp",
    }
    fields.update(overrides)
    return HookContext(**fields)  # type: ignore[arg-type]


def test_evaluate_records_payload_and_returns_noop() -> None:
    with mock.patch("yoke_core.domain.observe_cli.record_hook_event") as record:
        decision = evaluate(_context())
    assert decision.outcome is Outcome.NOOP
    assert decision.next is Next.CONTINUE
    record.assert_called_once()
    args, kwargs = record.call_args
    assert args[0]["tool_use_id"] == "tu-1"
    assert kwargs["session_id"] == "sess-1"
    assert kwargs["hook_event"] == "PostToolUse"
    assert kwargs["tool_use_id"] == "tu-1"
    assert kwargs["project_dir"] == "/tmp"


def test_evaluate_empty_payload_skips_record() -> None:
    with mock.patch("yoke_core.domain.observe_cli.record_hook_event") as record:
        decision = evaluate(_context(payload={}))
    assert decision.outcome is Outcome.NOOP
    record.assert_not_called()


def test_evaluate_swallows_record_failure() -> None:
    with mock.patch(
        "yoke_core.domain.observe_cli.record_hook_event",
        side_effect=RuntimeError("boom"),
    ):
        decision = evaluate(_context())
    assert decision.outcome is Outcome.NOOP
    assert decision.next is Next.CONTINUE
