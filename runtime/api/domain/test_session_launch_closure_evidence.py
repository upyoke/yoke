"""A launch the control plane closes itself says what it observed."""

from __future__ import annotations

import json

from yoke_core.domain.session_launch_closure_evidence import (
    TRANSPORT_RELAY_CONNECTED,
    TRANSPORT_RELAY_DISCONNECTED,
    TRANSPORT_RELAY_UNKNOWN,
    launch_phase_reached,
    relay_transport_state,
)
from yoke_core.domain.session_launch_deadlines import settle_launch_deadlines
from yoke_core.domain.session_launch_store import get_launch
from yoke_core.domain.session_relay import claim_relay_job
from yoke_core.domain.session_relay_types import RelayHeartbeat
from runtime.api.domain.session_launch_test_support import (
    NOW,
    add_relay,
    assigned_launch,
    launch_connection,
)


MACHINE_ID = "11111111-1111-4111-8111-111111111111"
RELAY_ID = f"machine:{MACHINE_ID}"
# Past the launch lease but inside the relay's connection horizon, so the
# relay is provably still talking to the control plane at expiry.
LEASE_EXPIRED_AT = "2026-08-22T12:05:01Z"
# Past the relay connection horizon too: the machine has gone quiet.
RELAY_SILENT_AT = "2026-08-22T12:25:00Z"


def _connection():
    conn = launch_connection()
    conn.execute("ALTER TABLE projects ADD COLUMN org_id INTEGER DEFAULT 1")
    conn.execute("CREATE TABLE organizations (id INTEGER PRIMARY KEY, settings TEXT)")
    conn.execute("INSERT INTO organizations VALUES (1, '{}')")
    for column in (
        "executor TEXT DEFAULT 'codex'",
        "execution_lane TEXT",
        "last_heartbeat TEXT",
        "offered_at TEXT",
        "ended_at TEXT",
        "last_tool_call_at TEXT",
        "turn_posture TEXT NOT NULL DEFAULT 'unknown'",
        "turn_posture_at TEXT",
    ):
        conn.execute(f"ALTER TABLE harness_sessions ADD COLUMN {column}")
    conn.commit()
    return conn


def _heartbeat() -> RelayHeartbeat:
    return RelayHeartbeat(
        relay_id=RELAY_ID,
        actor_id=1,
        machine_id=MACHINE_ID,
        hostname="relay-host",
        relay_version="0.1.1",
        surface_versions={"codex-cli": "0.148.0a15"},
        project_ids=(10,),
    )


def _claimed_launch(conn, *, key: str):
    add_relay(conn, relay_id=RELAY_ID, machine_id=MACHINE_ID)
    launch = assigned_launch(conn, key=key, machine_id=MACHINE_ID)
    outcome = claim_relay_job(
        conn, _heartbeat(), wait_seconds=0, now_provider=lambda: NOW
    )
    assert len(outcome.jobs) == 1
    return launch


def _relay_connected_through(conn, horizon: str) -> None:
    """Represent a relay that kept polling right through the expiry.

    Claiming a job sets the connection horizon from that single poll, so a
    fixture that never polls again looks silent by the time a five-minute
    launch lease runs out. A live relay polls throughout, which is exactly
    the case the transport marker has to tell apart from a silent one.
    """
    conn.execute(
        "UPDATE session_relays SET last_seen_at=?, connected_until=? WHERE relay_id=?",
        (horizon, horizon, RELAY_ID),
    )
    conn.commit()


def _attempt(conn, launch_id: str):
    return conn.execute(
        "SELECT completed_at,result_code,evidence FROM session_launch_attempts "
        "WHERE launch_id=?",
        (launch_id,),
    ).fetchone()


def _open_lease(conn, launch_id: str) -> str:
    return conn.execute(
        "SELECT lease_id FROM session_launch_attempts WHERE launch_id=?",
        (launch_id,),
    ).fetchone()[0]


def test_lease_expiry_records_phase_and_diagnostics_on_the_open_attempt() -> None:
    conn = _connection()
    launch = _claimed_launch(conn, key="lease-expiry-evidence")
    _relay_connected_through(conn, "2026-08-22T12:10:00Z")

    settle_launch_deadlines(conn, now=LEASE_EXPIRED_AT)

    attempt = _attempt(conn, launch.launch_id)
    # The attempt stays open so a late native report can still settle it,
    # but it no longer waits with nothing to diagnose.
    assert attempt[0] is None
    evidence = json.loads(attempt[2])
    assert evidence["result_code"] == "launch_lease_expired"
    assert evidence["closure_reason"] == "launch_lease_expiry"
    assert evidence["launch_phase_reached"] == "launching"
    assert evidence["relay_id"] == RELAY_ID
    assert evidence["machine_id"] == MACHINE_ID
    assert evidence["duration_ms"] == 301_000


def test_lease_expiry_surfaces_the_terminal_result_code_on_the_launch_row() -> None:
    conn = _connection()
    launch = _claimed_launch(conn, key="lease-expiry-launch-row")

    settle_launch_deadlines(conn, now=LEASE_EXPIRED_AT)

    settled = get_launch(conn, launch.launch_id)
    assert settled.state == "outcome_unknown"
    assert settled.result_code == "launch_lease_expired"
    # The launch row carries the same document the attempt does, so an
    # operator reading either surface gets the same answer.
    assert json.loads(settled.result_evidence) == json.loads(
        _attempt(conn, launch.launch_id)[2]
    )


def test_a_connected_relay_at_expiry_reads_as_an_adapter_stall() -> None:
    conn = _connection()
    launch = _claimed_launch(conn, key="connected-relay-expiry")
    _relay_connected_through(conn, "2026-08-22T12:10:00Z")

    settle_launch_deadlines(conn, now=LEASE_EXPIRED_AT)

    evidence = json.loads(_attempt(conn, launch.launch_id)[2])
    assert evidence["transport_state"] == TRANSPORT_RELAY_CONNECTED


def test_a_silent_relay_at_expiry_reads_as_transport_degradation() -> None:
    conn = _connection()
    launch = _claimed_launch(conn, key="silent-relay-expiry")

    settle_launch_deadlines(conn, now=RELAY_SILENT_AT)

    evidence = json.loads(_attempt(conn, launch.launch_id)[2])
    assert evidence["transport_state"] == TRANSPORT_RELAY_DISCONNECTED


def test_a_late_native_report_lands_on_top_of_the_expiry_document() -> None:
    from yoke_core.domain.session_launch_execution import report_launch_attempt

    conn = _connection()
    add_relay(conn, relay_id=RELAY_ID, machine_id=MACHINE_ID)
    launch = assigned_launch(conn, key="late-report", machine_id=MACHINE_ID)
    outcome = claim_relay_job(
        conn, _heartbeat(), wait_seconds=0, now_provider=lambda: NOW
    )
    job = outcome.jobs[0]
    settle_launch_deadlines(conn, now=LEASE_EXPIRED_AT)

    report_launch_attempt(
        conn,
        launch_id=launch.launch_id,
        lease_id=job.lease_id,
        result_code="native_created",
        native_session_id="native-1",
        evidence={"surface": "codex-cli", "native_launch_phase": "native_running"},
        now="2026-08-22T12:05:30Z",
    )

    evidence = json.loads(_attempt(conn, launch.launch_id)[2])
    # The native facts win where the two documents overlap, and the expiry
    # context survives underneath: that the control plane had already given
    # up on this attempt is precisely what makes a late native worth
    # reconciling rather than a puzzle.
    assert evidence["native_launch_phase"] == "native_running"
    assert evidence["surface"] == "codex-cli"
    assert evidence["closure_reason"] == "launch_lease_expiry"
    assert evidence["launch_phase_reached"] == "launching"


def test_phase_reached_names_the_furthest_observed_launch_state() -> None:
    conn = _connection()
    launch = _claimed_launch(conn, key="phase-ladder")

    # Reading the row back after the relay leased it shows the ladder has
    # advanced, which is exactly what a closure needs to report.
    assert launch_phase_reached(get_launch(conn, launch.launch_id)) == "launching"
    assert launch_phase_reached(launch) == "assigned"


def test_transport_state_is_unknown_without_a_relay_row() -> None:
    conn = _connection()

    assert (
        relay_transport_state(conn, relay_id=None, now=NOW) == TRANSPORT_RELAY_UNKNOWN
    )
    assert (
        relay_transport_state(conn, relay_id="machine:absent", now=NOW)
        == TRANSPORT_RELAY_UNKNOWN
    )


def test_a_cancelled_launch_still_closes_with_phase_and_transport() -> None:
    """The one closure no earlier pass reaches still says what it observed.

    Cancelling a launching launch moves it to ``outcome_unknown`` pending
    reconciliation, which the deadline pass no longer selects. The relay
    batch expiring is then the first thing to touch the attempt, so that
    closure has to compose the document rather than inherit one.
    """
    from yoke_core.domain.session_launch_requests import cancel_launch
    from yoke_core.domain.session_relay_expiry import settle_expired_relay_leases
    from runtime.api.domain.session_launch_test_support import authorization

    conn = _connection()
    launch = _claimed_launch(conn, key="cancelled-then-expired")
    _relay_connected_through(conn, "2026-08-22T12:10:00Z")
    cancel_launch(
        conn,
        launch_id=launch.launch_id,
        auth=authorization(),
        now="2026-08-22T12:01:00Z",
    )

    settle_expired_relay_leases(conn, now=LEASE_EXPIRED_AT)

    attempt = _attempt(conn, launch.launch_id)
    assert attempt[0] == LEASE_EXPIRED_AT
    evidence = json.loads(attempt[2])
    assert evidence["result_code"] == "relay_lease_expired"
    assert evidence["closure_reason"] == "relay_lease_expiry"
    assert evidence["launch_phase_reached"] == "launching"
    assert evidence["transport_state"] == TRANSPORT_RELAY_CONNECTED
    assert evidence["relay_id"] == RELAY_ID
    assert evidence["machine_id"] == MACHINE_ID


def test_lease_expiry_keeps_what_the_relay_already_reported() -> None:
    """The closure adds to the relay's account of itself, never replaces it.

    A relay that reported its spawn phase before going quiet left the most
    diagnosable fact on the row. Overwriting it at expiry would destroy
    exactly what recording a closure exists to preserve.
    """
    from yoke_core.domain.session_relay import report_relay_job

    conn = _connection()
    launch = _claimed_launch(conn, key="expiry-keeps-relay-report")
    _relay_connected_through(conn, "2026-08-22T12:10:00Z")
    report_relay_job(
        conn,
        actor_id=1,
        relay_id=RELAY_ID,
        job_kind="launch",
        job_id=launch.launch_id,
        lease_id=_open_lease(conn, launch.launch_id),
        result_code="progress",
        adapter_revision="codex-relay-v4",
        evidence={"result_code": "transport_exception", "native_launch_phase": "spawn"},
        now="2026-08-22T12:00:20Z",
    )

    settle_launch_deadlines(conn, now=LEASE_EXPIRED_AT)

    evidence = json.loads(_attempt(conn, launch.launch_id)[2])
    assert evidence["native_launch_phase"] == "spawn"
    # The closure's terminal code wins where the two documents overlap.
    assert evidence["result_code"] == "launch_lease_expired"
    assert evidence["closure_reason"] == "launch_lease_expiry"
