"""A desktop conversation is woken by its operator, never by Yoke.

The failure these cover is a fork, not an error: the relay resumed an
operator-opened Claude Desktop session headlessly, the reply was processed,
and the person's next typed sentence continued the branch their app was
still showing. So the assertions are about what does *not* happen — no
native route composed at any version, no peer binary named, no grant that
reopens it — plus the two things that replace it: the envelope still waits
for hook injection, and its operator is told it is waiting.
"""

from __future__ import annotations

from datetime import timedelta

import pytest

from yoke_contracts.session_control.capabilities import (
    SESSION_SURFACE_CAPABILITIES,
    native_wake_supported,
    surface_wake_authority,
)
from yoke_contracts.session_control.surface_versions import (
    machine_wake_surface,
    surface_operation_supported,
)
from yoke_core.domain.session_relay_versions import wake_versions_supported
from yoke_core.domain.actor_message_recipients import ACTOR_KIND
from yoke_core.domain.session_manual_wake import request_session_wake
from yoke_core.domain.session_message_routing import messageability
from yoke_core.domain.session_message_service import send_message
from yoke_core.domain.session_message_types import SessionMessageError
from yoke_core.domain.session_message_wake import wake_eligible_recipients
from yoke_core.domain.session_operator_wake_notice import notify_operator_to_wake
from runtime.api.domain.test_session_message_support import (
    NOW,
    NOW_TEXT,
    message_connection,
    selector,
)


DESKTOP_SURFACES = ("claude-desktop", "codex-desktop", "cursor-desktop")
CLI_SURFACES = ("claude-cli", "codex-cli", "cursor-cli")
#: ``fleet.wake_ack_grace_seconds`` — the window every starvation test reuses.
GRACE = timedelta(seconds=300)
STARVED = NOW + GRACE + timedelta(seconds=1)
CLAUDE_DESKTOP_SESSION_ID = "s-desktop"
CLAUDE_DESKTOP_VERSION = "1.32885.1"


def _add_desktop_session(conn, *, session_id: str = CLAUDE_DESKTOP_SESSION_ID) -> None:
    conn.execute(
        "INSERT INTO harness_sessions ("
        "session_id,project_id,actor_id,executor,executor_surface,"
        "executor_version,machine_id,execution_lane,last_heartbeat,"
        "last_tool_call_at,offered_at) "
        "VALUES (?,1,10,'claude-code','claude-desktop',?,'m5','direct',?,?,?)",
        (session_id, CLAUDE_DESKTOP_VERSION, NOW_TEXT, NOW_TEXT, NOW_TEXT),
    )
    conn.commit()


def _send_to(conn, session_id: str) -> str:
    return send_message(
        conn,
        actor_id=10,
        sender_session_id="s2",
        selector=selector(session_ids=[session_id]),
        body="Read the plan and report what you would change.",
        now=NOW,
    )["message_id"]


def _operator_notices(conn, *, actor_id: int = 10) -> list[str]:
    """Bodies of every notice standing for one operator.

    Read straight from the stored rows rather than through the Inbox
    composer: that reader bounds messages by wall-clock expiry, and these
    fixtures live at a fixed simulated ``NOW``.
    """
    rows = conn.execute(
        "SELECT m.body FROM actor_message_recipients r "
        "JOIN session_messages m ON m.message_id=r.message_id "
        "WHERE r.recipient_kind=? AND r.actor_id=? AND r.state='pending' "
        "ORDER BY m.created_at,m.message_id",
        (ACTOR_KIND, actor_id),
    ).fetchall()
    return [str(row[0]) for row in rows]


def _go_quiet(conn, session_id: str, *, when) -> None:
    """Fresh heartbeat, no tool call since the send — an unattended window."""
    conn.execute(
        "UPDATE harness_sessions SET last_heartbeat=? WHERE session_id=?",
        (when.strftime("%Y-%m-%dT%H:%M:%SZ"), session_id),
    )
    conn.commit()


@pytest.mark.parametrize("surface", DESKTOP_SURFACES)
def test_every_desktop_surface_declares_its_operator_as_the_waker(surface) -> None:
    assert surface_wake_authority(surface) == "operator"
    assert not native_wake_supported(surface)


@pytest.mark.parametrize("surface", CLI_SURFACES)
def test_cli_surfaces_keep_their_existing_declaration(surface) -> None:
    assert surface_wake_authority(surface) == "native"
    assert native_wake_supported(surface)


@pytest.mark.parametrize("surface", DESKTOP_SURFACES)
@pytest.mark.parametrize("liveness", ("active", "stale", "ended"))
@pytest.mark.parametrize("wake_mode", ("idle_timeout", "waiting"))
def test_no_wake_route_is_version_qualified_on_a_desktop_surface(
    surface, liveness, wake_mode
) -> None:
    """The relay's version gate refuses before any binary is chosen.

    The refusal is not "this version is too old" — the surface's own
    version and a fully qualified peer are both supplied here — it is that
    no version of anything may resume this window.
    """
    version = SESSION_SURFACE_CAPABILITIES[surface].minimum_version

    assert not wake_versions_supported(surface, version, version, wake_mode, liveness)


@pytest.mark.parametrize("surface", DESKTOP_SURFACES)
def test_a_desktop_surface_keeps_its_hook_delivery_capability(surface) -> None:
    """Only the resume is refused; the operator's next turn still delivers.

    Refusing at the surface's messaging capability instead would also close
    the hook-route acknowledgement proof the live-acceptance matrix rests
    on, and hook delivery is exactly the route this ruling preserves. So
    `claude-desktop`'s private `message_active` stays qualifiable while
    every wake route above it is shut.
    """
    capability = SESSION_SURFACE_CAPABILITIES[surface]

    assert capability.inject_events
    assert surface_operation_supported(
        surface, capability.minimum_version, "message_active"
    ) is (capability.message_active != "none")


def test_no_peer_binary_is_named_for_a_desktop_target() -> None:
    installed = {"claude-cli": "2.1.241", "cursor-cli": "2026.08.11-e8db854"}

    for surface in DESKTOP_SURFACES:
        for operation in ("message_idle", "message_stopped"):
            assert machine_wake_surface(surface, installed, operation) is None
    # The peer route itself is intact for the surfaces it was built for.
    assert machine_wake_surface("claude-vscode", installed, "message_stopped") == (
        "claude-cli",
        "2.1.241",
    )


def test_routing_names_the_operator_as_the_wake_authority() -> None:
    row = {
        "executor_surface": "claude-desktop",
        "executor_version": CLAUDE_DESKTOP_VERSION,
    }
    routing = messageability(
        row, liveness="stale", machine_surface_versions={"claude-cli": "2.1.241"}
    )
    assert routing["wake_authority"] == "operator"
    assert routing["wake_interface"] == "none"
    # Delivery is unchanged: the hook still carries the message.
    assert routing["messageable"] is True
    assert routing["hook_injection"] is True


def test_a_starved_desktop_envelope_is_never_woken_and_stays_pending() -> None:
    conn = message_connection()
    _add_desktop_session(conn)
    message_id = _send_to(conn, CLAUDE_DESKTOP_SESSION_ID)
    _go_quiet(conn, CLAUDE_DESKTOP_SESSION_ID, when=STARVED)

    assert wake_eligible_recipients(conn, now=STARVED) == []
    state = conn.execute(
        "SELECT state FROM session_message_recipients WHERE message_id=?",
        (message_id,),
    ).fetchone()[0]
    assert state == "pending"
    skip = conn.execute(
        "SELECT result_code,evidence FROM session_message_attempts WHERE message_id=?",
        (message_id,),
    ).fetchone()
    assert skip["result_code"] == "skipped_operation"
    assert "surface_wake_operator_driven" in skip["evidence"]


def test_the_operator_is_told_which_chat_holds_the_waiting_message() -> None:
    conn = message_connection()
    _add_desktop_session(conn)
    _send_to(conn, CLAUDE_DESKTOP_SESSION_ID)
    _go_quiet(conn, CLAUDE_DESKTOP_SESSION_ID, when=STARVED)

    wake_eligible_recipients(conn, now=STARVED)

    notices = [
        body for body in _operator_notices(conn) if CLAUDE_DESKTOP_SESSION_ID in body
    ]
    assert len(notices) == 1
    assert "type anything" in notices[0]


def test_one_waiting_envelope_produces_one_notice() -> None:
    conn = message_connection()
    _add_desktop_session(conn)
    _send_to(conn, CLAUDE_DESKTOP_SESSION_ID)
    _go_quiet(conn, CLAUDE_DESKTOP_SESSION_ID, when=STARVED)

    wake_eligible_recipients(conn, now=STARVED)
    wake_eligible_recipients(conn, now=STARVED + timedelta(seconds=60))

    assert len(_operator_notices(conn)) == 1


def test_no_notice_before_the_grace_window_closes() -> None:
    conn = message_connection()
    _add_desktop_session(conn)
    _send_to(conn, CLAUDE_DESKTOP_SESSION_ID)
    early = NOW + GRACE - timedelta(seconds=1)
    _go_quiet(conn, CLAUDE_DESKTOP_SESSION_ID, when=early)

    wake_eligible_recipients(conn, now=early)

    assert _operator_notices(conn) == []


def test_an_injected_desktop_envelope_owes_its_operator_nothing() -> None:
    conn = message_connection()
    _add_desktop_session(conn)
    message_id = _send_to(conn, CLAUDE_DESKTOP_SESSION_ID)
    conn.execute(
        "UPDATE session_message_recipients SET injection_count=1,"
        "last_injected_at=? WHERE message_id=?",
        (NOW_TEXT, message_id),
    )
    conn.commit()
    row = conn.execute(
        "SELECT r.*,m.created_at AS message_created_at,hs.ended_at,hs.terminated_at "
        "FROM session_message_recipients r "
        "JOIN session_messages m ON m.message_id=r.message_id "
        "JOIN harness_sessions hs ON hs.session_id=r.session_id "
        "WHERE r.message_id=?",
        (message_id,),
    ).fetchone()

    assert notify_operator_to_wake(conn, dict(row), now=STARVED) is None


def test_session_wake_refuses_a_desktop_recipient_with_the_delivery_route() -> None:
    conn = message_connection()
    _add_desktop_session(conn)

    with pytest.raises(SessionMessageError) as raised:
        request_session_wake(
            conn,
            actor_id=10,
            caller_session_id="s2",
            session_id=CLAUDE_DESKTOP_SESSION_ID,
            public_ref=None,
            prompt=None,
            now=NOW,
        )
    assert raised.value.code == "operator_wake_required"
    assert "yoke say --session" in str(raised.value)
