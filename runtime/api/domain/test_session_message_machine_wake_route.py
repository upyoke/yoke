"""A stopped Claude app is woken by the CLI its own machine reports installed."""

from __future__ import annotations

import json
from datetime import timedelta

from yoke_core.domain.session_message_service import send_message
from yoke_core.domain.session_message_store import message_details, public_recipients
from yoke_core.domain.session_message_wake import wake_eligible_recipients
from yoke_core.domain.session_relay import claim_relay_job
from yoke_core.domain.session_relay_types import RelayHeartbeat
from runtime.api.domain.test_session_message_support import (
    NOW,
    NOW_TEXT,
    message_connection,
    selector,
)


MACHINE_ID = "22222222-2222-4222-8222-222222222222"
RELAY_ID = f"machine:{MACHINE_ID}"
DESKTOP_VERSION = "1.32885.1"
QUALIFIED_CLI = "2.1.241"
BELOW_FLOOR_CLI = "2.1.200"
WAKE_TIME = "2026-08-22T16:11:00Z"


def _stopped_desktop_connection():
    """A claude-desktop session that has ended, on a relay-served machine."""
    conn = message_connection()
    conn.execute(
        "UPDATE harness_sessions SET executor='claude-code',"
        "executor_surface='claude-desktop',executor_version=?,machine_id=?,"
        "ended_at=? WHERE session_id='s2'",
        (DESKTOP_VERSION, MACHINE_ID, NOW_TEXT),
    )
    conn.commit()
    return conn


def _register_relay(conn, surface_versions: dict[str, str]) -> None:
    conn.execute(
        "INSERT INTO session_relays (relay_id,actor_id,machine_id,hostname,"
        "relay_version,surface_versions,project_checkouts,first_seen_at,"
        "last_seen_at,connected_until,state) VALUES (?,?,?,?,?,?,?,?,?,?,'active')",
        (
            RELAY_ID,
            10,
            MACHINE_ID,
            "dev-relay",
            "0.1.1",
            json.dumps(surface_versions),
            json.dumps([1]),
            NOW_TEXT,
            NOW_TEXT,
            "2026-08-23T00:00:00Z",
        ),
    )
    conn.commit()


def _heartbeat(surface_versions: dict[str, str]) -> RelayHeartbeat:
    return RelayHeartbeat(
        relay_id=RELAY_ID,
        actor_id=10,
        machine_id=MACHINE_ID,
        hostname="dev-relay",
        relay_version="0.1.1",
        surface_versions=dict(surface_versions),
        project_ids=(1,),
    )


def _send(conn) -> str:
    return str(
        send_message(
            conn,
            actor_id=10,
            sender_session_id="s1",
            selector=selector(session_ids=["s2"]),
            body="Body stays server-side through every wake route.",
            now=NOW,
        )["message_id"]
    )


def _snapshot_route(conn, message_id: str) -> dict:
    recipient = public_recipients(message_details(conn, message_id))[0]
    return dict(recipient["messageability"])


def test_send_snapshot_routes_a_stopped_desktop_session_through_the_machine_cli():
    conn = _stopped_desktop_connection()
    _register_relay(conn, {"claude-cli": QUALIFIED_CLI})

    routing = _snapshot_route(conn, _send(conn))

    assert routing["wake_operation"] == "message_stopped"
    assert routing["wake_interface"] == "supported"


def test_send_snapshot_reports_no_route_without_a_qualified_machine_cli():
    bare = _stopped_desktop_connection()
    assert _snapshot_route(bare, _send(bare))["wake_interface"] == "none"

    stale = _stopped_desktop_connection()
    _register_relay(stale, {"claude-cli": BELOW_FLOOR_CLI})
    assert _snapshot_route(stale, _send(stale))["wake_interface"] == "none"


def test_machine_cli_makes_a_stopped_desktop_recipient_wake_eligible():
    conn = _stopped_desktop_connection()
    _send(conn)
    assert wake_eligible_recipients(conn, now=NOW + timedelta(minutes=11)) == []

    _register_relay(conn, {"claude-cli": QUALIFIED_CLI})
    eligible = wake_eligible_recipients(conn, now=NOW + timedelta(minutes=11))

    assert [row["session_id"] for row in eligible] == ["s2"]
    assert eligible[0]["executor_surface"] == "claude-desktop"


def test_wake_job_carries_the_executing_cli_rather_than_the_registered_surface():
    conn = _stopped_desktop_connection()
    _register_relay(conn, {"claude-cli": QUALIFIED_CLI})
    message_id = _send(conn)

    outcome = claim_relay_job(
        conn,
        _heartbeat({"claude-cli": QUALIFIED_CLI}),
        wait_seconds=0,
        now_provider=lambda: WAKE_TIME,
    )

    # Wakes stay serial, so one poll leases exactly one of them.
    assert len(outcome.jobs) == 1
    job = outcome.jobs[0]
    assert job.message_id == message_id
    assert job.target_session_id == "s2"
    assert job.wake_route == "direct"
    # The relay dispatches by job surface, and claude-desktop has no resume
    # adapter, so the job must name the binary that performs the resume.
    assert job.surface == "claude-cli"
    assert job.surface_version == QUALIFIED_CLI


def test_no_wake_job_is_minted_when_the_machine_cli_is_below_its_floor():
    conn = _stopped_desktop_connection()
    _register_relay(conn, {"claude-cli": BELOW_FLOOR_CLI})
    _send(conn)

    outcome = claim_relay_job(
        conn,
        _heartbeat({"claude-cli": BELOW_FLOOR_CLI}),
        wait_seconds=0,
        now_provider=lambda: WAKE_TIME,
    )

    assert outcome.jobs == ()
    assert (
        conn.execute(
            "SELECT wake_attempt_count FROM session_message_recipients"
        ).fetchone()[0]
        == 0
    )
