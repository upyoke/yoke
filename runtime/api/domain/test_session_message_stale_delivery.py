"""Every declared surface keeps its hook route and its own wake authority."""

from datetime import timedelta

import pytest

from yoke_contracts.session_control.capabilities import SESSION_SURFACE_CAPABILITIES
from yoke_contracts.session_control.surface_versions import machine_wake_surface
from yoke_core.domain.session_message_delivery import lease_for_hook
from yoke_core.domain.session_message_lease_complete import complete_hook_lease
from yoke_core.domain.session_message_wake import wake_eligible_recipients
from runtime.api.domain.session_message_machine_wake_route_test_support import (
    _register_relay,
    _send,
    _surface_connection,
)
from runtime.api.domain.session_message_support_test_support import NOW


@pytest.mark.parametrize("surface", SESSION_SURFACE_CAPABILITIES)
def test_stale_running_surface_delivers_at_its_declared_hook(monkeypatch, surface):
    cap = SESSION_SURFACE_CAPABILITIES[surface]
    executor = "claude-code" if surface.startswith("claude-") else surface.split("-")[0]
    conn = _surface_connection(
        executor=executor, surface=surface, version=cap.minimum_version, ended=False
    )
    _register_relay(
        conn, {s: c.minimum_version for s, c in SESSION_SURFACE_CAPABILITIES.items()}
    )
    message = _send(conn)
    candidates = wake_eligible_recipients(conn, now=NOW + timedelta(minutes=11))
    if cap.wake_authority == "operator":
        assert candidates == []
        assert (
            conn.execute(
                "SELECT wake_attempt_count FROM session_message_recipients "
                "WHERE message_id=?",
                (message,),
            ).fetchone()[0]
            == 0
        )
    elif (
        cap.message_stopped != "none"
        or machine_wake_surface(
            surface,
            {s: c.minimum_version for s, c in SESSION_SURFACE_CAPABILITIES.items()},
            "message_stopped",
            "yoke",
        )
        is not None
    ):
        assert candidates[0]["message_id"] == message
        assert candidates[0]["wake_mode"] == "waiting"
    else:
        assert candidates == []
        assert (
            conn.execute(
                "SELECT wake_attempt_count FROM session_message_recipients "
                "WHERE message_id=?",
                (message,),
            ).fetchone()[0]
            == 1
        )
    monkeypatch.setattr(
        "yoke_core.domain.session_message_delivery.utc_now", lambda: NOW
    )
    lease = lease_for_hook(
        conn, session_id="s2", hook_event=cap.inject_events[0], limit=10
    )
    assert lease["messages"][0]["message_id"] == message
    assert (
        complete_hook_lease(
            conn, lease_id=lease["lease_id"], injected=True, result="injected"
        )
        == 1
    )
    assert (
        conn.execute(
            "SELECT state FROM session_message_recipients WHERE message_id=?",
            (message,),
        ).fetchone()[0]
        == "injected"
    )
