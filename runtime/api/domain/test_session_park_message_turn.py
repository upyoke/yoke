# ruff: noqa: F811
"""A prompt and its message receipts do not abandon a declared wait."""

from datetime import timedelta

import pytest

from runtime.api.sessions_test_support import _register, conn  # noqa: F401
from runtime.api.domain.test_session_parked_mode import _ensure_turn_posture
from yoke_contracts.timestamps import utc_now
from yoke_core.domain.session_activity_state import apply_envelope_state
from yoke_core.domain.session_mode import set_session_mode
from yoke_core.hooks.session_turn_posture_tail import persist_accepted_hook_turn_posture


@pytest.mark.parametrize(
    "reason", ["awaiting integration dependency", "awaiting parent decision"]
)
def test_message_only_turn_keeps_park_and_reason(conn, monkeypatch, reason):
    _register(conn)
    _ensure_turn_posture(conn)
    monkeypatch.setattr(conn, "close", lambda: None)
    set_session_mode(conn, "sess-1", "parked", reason=reason)
    start = utc_now() + timedelta(seconds=1)
    assert persist_accepted_hook_turn_posture(
        event_name="UserPromptSubmit",
        session_id="sess-1",
        observed_at=start,
        final_outcome="allow",
        timed_out=False,
        failed=False,
        connection_factory=lambda: conn,
    )
    for index, command in enumerate(
        ("yoke messages get message", "yoke messages acknowledge message")
    ):
        apply_envelope_state(
            conn,
            {
                "event_name": "HarnessToolCallCompleted",
                "session_id": "sess-1",
                "event_time": start + timedelta(seconds=index + 1),
                "tool_use_id": f"receipt-{index}",
                "tool_name": "Shell",
                "context": {"detail": {"tool_input": command}},
            },
        )
    assert persist_accepted_hook_turn_posture(
        event_name="Stop",
        session_id="sess-1",
        observed_at=start + timedelta(seconds=4),
        final_outcome="allow",
        timed_out=False,
        failed=False,
        connection_factory=lambda: conn,
    )
    row = conn.execute(
        "SELECT mode,quiet_reason FROM harness_sessions WHERE session_id='sess-1'"
    ).fetchone()
    assert (row["mode"], row["quiet_reason"]) == ("parked", reason)


def test_real_work_after_message_ends_park(conn):
    _register(conn)
    _ensure_turn_posture(conn)
    set_session_mode(conn, "sess-1", "parked", reason="awaiting evidence")
    apply_envelope_state(
        conn,
        {
            "event_name": "HarnessToolCallCompleted",
            "session_id": "sess-1",
            "event_time": utc_now() + timedelta(seconds=1),
            "tool_use_id": "work",
            "tool_name": "Edit",
            "context": {"detail": {"tool_input": "/lane/code.py"}},
        },
    )
    assert (
        conn.execute(
            "SELECT mode FROM harness_sessions WHERE session_id='sess-1'"
        ).fetchone()[0]
        == "wait"
    )
