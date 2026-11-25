"""A successful hook completion respects a park written by that shell call."""

from __future__ import annotations

from datetime import timedelta

import pytest

from runtime.api.domain.test_session_parked_mode import _ensure_turn_posture
from runtime.api.sessions_test_support import _register, conn  # noqa: F401
from yoke_contracts.harness_shell_tools import SHELL_KIND_PAYLOAD_KEY
from yoke_contracts.hook_tool_names import canonicalize_shell_payload
from yoke_contracts.timestamps import utc_now
from yoke_core.domain import observe_event_emission
from yoke_core.domain.observe_parsing import parse_hook_event
from yoke_core.domain.session_activity_state import apply_envelope_state
from yoke_core.domain.session_mode import set_session_mode


@pytest.mark.parametrize(
    ("native_tool", "stamp", "shell_kind"),
    [
        pytest.param("Bash", "bash", "bash", id="claude-bash"),
        pytest.param("PowerShell", "powershell", "powershell", id="claude-powershell"),
        pytest.param("shell", "bash", "bash", id="codex-shell"),
        pytest.param("Bash", "powershell", "powershell", id="codex-windows"),
        pytest.param("Bash", None, "bash", id="codex-unstamped"),
        pytest.param("Shell", "powershell", "powershell", id="cursor-windows"),
    ],
)
@pytest.mark.parametrize("explicit_park", [True, False])
def test_shell_completion_respects_explicit_park(
    conn, monkeypatch, native_tool, stamp, shell_kind, explicit_park  # noqa: F811
):
    _register(conn)
    _ensure_turn_posture(conn)
    set_session_mode(conn, "sess-1", "parked", reason="awaiting delivery")
    completed_at = utc_now() + timedelta(seconds=1)
    monkeypatch.setattr(observe_event_emission, "utc_now", lambda: completed_at)

    if shell_kind == "powershell":
        command = "yoke messages get m --json | Out-Null"
        touch = "yoke sessions touch `\n --mode parked --reason 'awaiting delivery'"
    else:
        command = "yoke messages get m --json > /dev/null"
        touch = "yoke sessions touch --mode parked --reason 'awaiting delivery'"
    if explicit_park:
        command = f"{command}; {touch}"

    payload = {"tool_name": native_tool, "tool_input": {"command": command}}
    if stamp is not None:
        payload[SHELL_KIND_PAYLOAD_KEY] = stamp
    record = parse_hook_event(
        canonicalize_shell_payload(payload),
        session_id="sess-1",
        hook_event="PostToolUse",
        tool_use_id="call-1",
    )
    assert record is not None
    envelope = observe_event_emission.build_envelope(record)
    assert envelope["event_name"] == "HarnessToolCallCompleted"
    assert envelope["context"]["detail"]["shell_kind"] == shell_kind
    apply_envelope_state(conn, envelope)

    row = conn.execute(
        "SELECT mode, quiet_reason FROM harness_sessions WHERE session_id = 'sess-1'"
    ).fetchone()
    expected = ("parked", "awaiting delivery") if explicit_park else ("wait", None)
    assert (row["mode"], row["quiet_reason"]) == expected
