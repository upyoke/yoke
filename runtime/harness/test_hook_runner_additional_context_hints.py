"""End-to-end ``additionalContext`` delivery for the three typed hint modules.

These tests load the real hint module (``hint_posttool_field_note``,
``hint_monitor_relay``, ``hint_file_line_limit_approach``) into a single-entry
chain, drive ``runtime.harness.hook_runner.runner.run_event`` with a realistic
stdin payload, and assert the rendered ``hookSpecificOutput.additionalContext``
envelope reaches stdout for both Claude and Codex.

Coverage map:

* AC-6 — ``hint_posttool_field_note`` on a non-zero Yoke CLI PostToolUse
  payload emits the canonical field-note footer.
* AC-7 — ``hint_monitor_relay`` on a Claude ``Monitor`` PreToolUse payload
  emits the relay-only reminder.
* AC-8 — ``hint_file_line_limit_approach`` on a ``Write`` payload that crosses
  the 350-line cap emits the cap-approach hint.

Renderer-contract coverage for synthetic decisions lives
in the sibling ``test_hook_runner_additional_context.py``; isolated renderer
unit coverage lives in ``test_hook_runner_decision_render.py``.
"""

from __future__ import annotations

import json
from typing import Any, Iterable

import pytest

from yoke_contracts.field_note_text import FOOTER as FIELD_NOTE_FOOTER
from yoke_core.domain.file_line_check import LIMIT as FILE_LINE_LIMIT
from runtime.harness.hook_runner import runner as runner_module
from runtime.harness.hook_runner.adapter_capability import AdapterCapability
from runtime.harness.hook_runner.decision_render import (
    render_claude_decision,
    render_codex_decision,
)


def _silence_telemetry(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in (
        "emit_hook_execution_failed",
        "emit_hook_guardrail_evaluated",
        "emit_hook_dispatch_telemetry",
    ):
        monkeypatch.setattr(runner_module._telemetry, name, lambda **k: None)


def _capability(
    monkeypatch: pytest.MonkeyPatch,
    *,
    family: str,
    chain: Iterable[str],
) -> AdapterCapability:
    monkeypatch.setattr(runner_module, "chain_for", lambda *a, **k: list(chain))
    renderer = render_claude_decision if family == "claude" else render_codex_decision
    return AdapterCapability(
        family=family,
        events=frozenset({"PreToolUse", "PostToolUse"}),
        payload_parser=lambda raw: json.loads(raw) if raw else {},
        decision_renderer=renderer,
    )


# ---------------------------------------------------------------------------
# hint_posttool_field_note through run_event.
# ---------------------------------------------------------------------------


def _post_tool_use_payload(command: str, exit_code: int) -> str:
    return json.dumps({
        "tool_name": "Bash",
        "tool_input": {"command": command},
        "tool_response": {"content": f"... output ...\nExit code {exit_code}\n"},
        "cwd": "/tmp",
        "session_id": "test-session",
    })


def test_field_note_through_runner_reaches_claude_output(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AC-6: a non-zero Yoke CLI exit produces the field-note footer."""
    capability = _capability(
        monkeypatch, family="claude",
        chain=["yoke_core.domain.hint_posttool_field_note"],
    )
    _silence_telemetry(monkeypatch)

    text, exit_code = runner_module.run_event(
        "PostToolUse",
        capability=capability,
        stdin_data=_post_tool_use_payload("yoke items get YOK-1", 2),
    )

    assert exit_code == 0
    payload = json.loads(text)
    hook = payload["hookSpecificOutput"]
    assert hook["hookEventName"] == "PostToolUse"
    assert FIELD_NOTE_FOOTER in hook["additionalContext"]


def test_field_note_through_runner_reaches_codex_output(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AC-6 + AC-4: same footer reaches Codex through the shared runner."""
    capability = _capability(
        monkeypatch, family="codex",
        chain=["yoke_core.domain.hint_posttool_field_note"],
    )
    _silence_telemetry(monkeypatch)

    text, exit_code = runner_module.run_event(
        "PostToolUse",
        capability=capability,
        stdin_data=_post_tool_use_payload(
            "python3 -m yoke_core.cli.db_router items get YOK-2", 1,
        ),
    )

    assert exit_code == 0
    payload = json.loads(text)
    hook = payload["hookSpecificOutput"]
    assert hook["hookEventName"] == "PostToolUse"
    assert FIELD_NOTE_FOOTER in hook["additionalContext"]


def test_field_note_zero_exit_emits_no_envelope(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Zero exit code -> no advisory, no envelope, plain empty allow."""
    capability = _capability(
        monkeypatch, family="claude",
        chain=["yoke_core.domain.hint_posttool_field_note"],
    )
    _silence_telemetry(monkeypatch)

    text, exit_code = runner_module.run_event(
        "PostToolUse",
        capability=capability,
        stdin_data=_post_tool_use_payload("yoke items get YOK-1", 0),
    )

    assert (text, exit_code) == ("", 0)


# ---------------------------------------------------------------------------
# hint_monitor_relay through run_event (Claude-only matcher).
# ---------------------------------------------------------------------------


def test_monitor_relay_through_runner_reaches_claude_output(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AC-7: Monitor PreToolUse payload triggers the relay reminder envelope."""
    capability = _capability(
        monkeypatch, family="claude",
        chain=["yoke_core.domain.hint_monitor_relay"],
    )
    _silence_telemetry(monkeypatch)

    payload = json.dumps({
        "tool_name": "Monitor",
        "tool_input": {"pattern": "FAILED|%\\]"},
        "session_id": "test-session",
        "cwd": "/tmp",
    })
    text, exit_code = runner_module.run_event(
        "PreToolUse", capability=capability, stdin_data=payload,
    )

    assert exit_code == 0
    envelope = json.loads(text)
    hook = envelope["hookSpecificOutput"]
    assert hook["hookEventName"] == "PreToolUse"
    assert "Monitor is a SUBSCRIPTION" in hook["additionalContext"]


def test_monitor_relay_non_monitor_tool_emits_no_envelope(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Non-Monitor PreToolUse calls do not produce the relay envelope."""
    capability = _capability(
        monkeypatch, family="claude",
        chain=["yoke_core.domain.hint_monitor_relay"],
    )
    _silence_telemetry(monkeypatch)

    payload = json.dumps({
        "tool_name": "Bash",
        "tool_input": {"command": "ls"},
    })
    text, exit_code = runner_module.run_event(
        "PreToolUse", capability=capability, stdin_data=payload,
    )

    assert (text, exit_code) == ("", 0)


# ---------------------------------------------------------------------------
# hint_file_line_limit_approach through run_event.
# ---------------------------------------------------------------------------


def test_file_line_limit_through_runner_reaches_claude_output(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Any,
) -> None:
    """AC-8: Write payload over the cap triggers the file-line-approach envelope."""
    monkeypatch.setenv("YOKE_REPO_ROOT", str(tmp_path))
    capability = _capability(
        monkeypatch, family="claude",
        chain=["yoke_core.domain.hint_file_line_limit_approach"],
    )
    _silence_telemetry(monkeypatch)

    over_cap = "x = 1\n" * (FILE_LINE_LIMIT + 5)
    target = tmp_path / "module_under_test.py"
    payload = json.dumps({
        "tool_name": "Write",
        "tool_input": {"file_path": str(target), "content": over_cap},
    })

    text, exit_code = runner_module.run_event(
        "PreToolUse", capability=capability, stdin_data=payload,
    )

    assert exit_code == 0
    envelope = json.loads(text)
    hook = envelope["hookSpecificOutput"]
    assert hook["hookEventName"] == "PreToolUse"
    assert "350-line authored-file cap" in hook["additionalContext"]
