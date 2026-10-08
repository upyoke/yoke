"""A launch's deadline window starts when its relay picks it up.

A launch assigned between relay polls retains its full registration window
once picked up, even when an earlier native has not reported yet.
"""

from __future__ import annotations

from yoke_contracts.timestamps import parse_instant

import json

import pytest

from yoke_core.domain.session_launch_deadlines import (
    LAUNCH_QUEUE_WAIT_SECONDS,
    settle_launch_deadlines,
)
from yoke_core.domain.session_launch_execution import claim_assigned_launch
from yoke_core.domain.session_launch_store import add_seconds, get_launch
from yoke_core.domain.session_launch_types import SessionLaunchError
from yoke_core.domain.session_relay_launch_lease import claim_next_launch
from yoke_core.domain.session_relay_types import RelayHeartbeat
from runtime.api.domain.session_launch_test_support import (
    NOW,
    add_relay,
    assigned_launch,
    launch_connection,
)


CREATE_DEADLINE = "2026-08-22T12:10:00Z"
PAST_CREATE_DEADLINE = "2026-08-22T12:15:00Z"
QUEUE_CAP = add_seconds(NOW, LAUNCH_QUEUE_WAIT_SECONDS)


def _heartbeat() -> RelayHeartbeat:
    return RelayHeartbeat(
        relay_id="relay-1",
        actor_id=1,
        machine_id="machine-1",
        hostname="relay-host",
        relay_version="source",
        surface_versions={"codex-cli": "0.148.0a15"},
        project_ids=(10,),
    )


def _message_expiry(conn, message_id: str) -> str:
    row = conn.execute(
        "SELECT expires_at FROM session_messages WHERE message_id = ?",
        (message_id,),
    ).fetchone()
    return str(row[0])


def _evidence(conn, launch_id: str) -> dict:
    return json.loads(get_launch(conn, launch_id).result_evidence or "{}")


def test_second_queued_launch_gets_its_full_window_from_pickup() -> None:
    conn = launch_connection()
    add_relay(conn, connected_until="2026-08-22T13:00:00Z")
    first = assigned_launch(conn, key="first")
    (held,) = claim_next_launch(conn, _heartbeat(), now=NOW)
    assert held.job_id == first.launch_id
    waiting = assigned_launch(conn, key="second")
    assert first.deadline_at == waiting.deadline_at == CREATE_DEADLINE

    settle_launch_deadlines(conn, now=PAST_CREATE_DEADLINE)
    assert get_launch(conn, waiting.launch_id).state == "assigned"

    (job,) = claim_next_launch(conn, _heartbeat(), now=PAST_CREATE_DEADLINE)

    assert job.job_id == waiting.launch_id
    assert job.deadline_at == parse_instant("2026-08-22T12:25:00Z")
    launched = get_launch(conn, waiting.launch_id)
    assert launched.state == "launching"
    assert launched.deadline_at == parse_instant("2026-08-22T12:25:00Z")
    assert _message_expiry(conn, waiting.message_id) == "2026-08-22T12:25:00Z"


def test_queued_launch_on_a_disconnected_relay_expires_at_its_create_deadline() -> None:
    conn = launch_connection()
    add_relay(conn, connected_until="2026-08-22T12:05:00Z")
    launch = assigned_launch(conn)

    settle_launch_deadlines(conn, now=PAST_CREATE_DEADLINE)

    closed = get_launch(conn, launch.launch_id)
    assert (closed.state, closed.result_code) == ("expired", "launch_deadline")
    evidence = _evidence(conn, launch.launch_id)
    assert evidence["closure_reason"] == "deadline_expiry"
    assert evidence["transport_state"] == "relay_disconnected"


def test_queue_cap_closes_a_launch_a_connected_relay_never_takes() -> None:
    conn = launch_connection()
    add_relay(conn, connected_until="2026-08-22T14:00:00Z")
    launch = assigned_launch(conn)

    assert settle_launch_deadlines(conn, now=add_seconds(QUEUE_CAP, -1)) == []
    settle_launch_deadlines(conn, now=QUEUE_CAP)

    closed = get_launch(conn, launch.launch_id)
    assert (closed.state, closed.result_code) == ("expired", "launch_deadline")
    evidence = _evidence(conn, launch.launch_id)
    assert evidence["closure_reason"] == "queue_wait_expiry"
    assert evidence["transport_state"] == "relay_connected"


def test_pickup_past_the_queue_cap_is_refused_with_its_recovery() -> None:
    conn = launch_connection()
    add_relay(conn, connected_until="2026-08-22T14:00:00Z")
    launch = assigned_launch(conn)

    with pytest.raises(SessionLaunchError) as refused:
        claim_assigned_launch(
            conn,
            launch_id=launch.launch_id,
            relay_id="relay-1",
            machine_id="machine-1",
            now=QUEUE_CAP,
        )

    assert refused.value.code == "expired"
    assert "queue_wait_expiry" in str(refused.value)
    assert f"launch retry {launch.launch_id}" in str(refused.value)
    assert get_launch(conn, launch.launch_id).state == "expired"
