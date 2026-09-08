"""The tool-call identity that correlates one hook dispatch row.

One tool call produces two ``HookDispatchTelemetry`` rows, one per hook
event. A reader that wants a specific call's phases has to name the call,
so both producers copy the harness payload's identity into the telemetry
context; without it the only join left is arrival order, which a
neighbouring hook or a late batch quietly invalidates.
"""

from __future__ import annotations

import json

import pytest

from yoke_core.hooks import telemetry


class _DispatchContext:
    session_id = ""
    executor_family = "claude"
    item_id = None
    tool_name = "Bash"
    now = None


class _AllowingDeadline:
    budget_ms = 5000

    def telemetry_allowed(self) -> bool:
        return True


def test_dispatch_record_names_the_call_it_is_a_phase_of(monkeypatch) -> None:
    """``flush_run_tail`` correlates the row with the tool call it timed."""
    from yoke_core.hooks import run_tail

    telem_records: list = []
    monkeypatch.setattr(telemetry, "flush_hook_telemetry", lambda *a, **k: None)
    monkeypatch.setattr(
        "yoke_core.hooks.session_turn_posture_tail.persist_accepted_hook_turn_posture",
        lambda **k: None,
    )

    run_tail.flush_run_tail(
        event_name="PostToolUse",
        context=_DispatchContext(),
        chain_length=1,
        final_outcome="allow",
        hook_wait_ms=3,
        timed_out=False,
        deadline=_AllowingDeadline(),
        payload={"tool_use_id": "call-77"},
        stdin_data="{}",
        controls=None,
        telem_records=telem_records,
    )

    assert telem_records[-1][1]["extra"]["tool_use_id"] == "call-77"


def test_dispatch_record_omits_an_identity_no_payload_carried(monkeypatch) -> None:
    """An uncorrelatable row says so rather than being attributed by order."""
    from yoke_core.hooks import run_tail

    telem_records: list = []
    monkeypatch.setattr(telemetry, "flush_hook_telemetry", lambda *a, **k: None)
    monkeypatch.setattr(
        "yoke_core.hooks.session_turn_posture_tail.persist_accepted_hook_turn_posture",
        lambda **k: None,
    )

    run_tail.flush_run_tail(
        event_name="UserPromptSubmit",
        context=_DispatchContext(),
        chain_length=1,
        final_outcome="allow",
        hook_wait_ms=3,
        timed_out=False,
        deadline=_AllowingDeadline(),
        payload={"tool_use_id": ""},
        stdin_data="{}",
        controls=None,
        telem_records=telem_records,
    )

    assert "tool_use_id" not in telem_records[-1][1]["extra"]


@pytest.mark.parametrize(
    ("family", "stdin_data", "expected"),
    [
        (
            "claude",
            json.dumps(
                {
                    "hook_event_name": "PreToolUse",
                    "tool_name": "Bash",
                    "tool_input": {"command": "true"},
                    "tool_use_id": "claude-call-1",
                }
            ),
            {"tool_use_id": "claude-call-1"},
        ),
        (
            "codex",
            json.dumps(
                {
                    "hook_event_name": "PreToolUse",
                    "tool_name": "apply_patch",
                    "tool_input": {"command": "*** Begin Patch"},
                    "tool_use_id": "codex-call-1",
                }
            ),
            {"tool_use_id": "codex-call-1"},
        ),
        # Cursor shell payloads carry no per-call identity, so a Cursor
        # dispatch row is honestly uncorrelatable rather than guessed at.
        (
            "cursor",
            json.dumps(
                {
                    "hook_event_name": "beforeShellExecution",
                    "command": "true",
                    "conversation_id": "cursor-conversation-1",
                }
            ),
            {},
        ),
    ],
)
def test_call_identity_reads_every_supported_harness_payload(
    family, stdin_data, expected
) -> None:
    """The identity is read from each harness's own parsed payload shape."""
    from yoke_contracts.hook_evaluator_protocol import hook_call_identity_fields
    from yoke_core.hooks.capability_resolve import resolve_capability

    payload = resolve_capability(family).payload_parser(stdin_data)

    assert hook_call_identity_fields(payload) == expected
