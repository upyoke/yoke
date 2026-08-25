"""Launch progress, expiry evidence, and terminal result-code tests."""

from __future__ import annotations

import json

from yoke_core.domain.session_relay import claim_relay_job, report_relay_job
from yoke_core.domain.session_relay_expiry import settle_expired_relay_leases
from yoke_core.domain.session_relay_types import RelayHeartbeat
from runtime.api.domain.session_launch_test_support import (
    NOW,
    add_relay,
    assigned_launch,
    relay_connection,
)


MACHINE_ID = "11111111-1111-4111-8111-111111111111"
RELAY_ID = f"machine:{MACHINE_ID}"
DIAGNOSTIC_REF = "nd-" + "a" * 32


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


def _claimed_launch(key: str):
    conn = relay_connection()
    add_relay(conn, relay_id=RELAY_ID, machine_id=MACHINE_ID)
    launch = assigned_launch(conn, key=key, machine_id=MACHINE_ID)
    claimed = claim_relay_job(
        conn,
        _heartbeat(),
        wait_seconds=0,
        now_provider=lambda: NOW,
    )
    assert len(claimed.jobs) == 1
    return conn, launch, claimed.jobs[0]


def _attempt(conn, launch_id: str):
    row = conn.execute(
        "SELECT completed_at,result_code,evidence FROM session_launch_attempts "
        "WHERE launch_id=?",
        (launch_id,),
    ).fetchone()
    return row, json.loads(row[2])


def test_relay_lease_expiry_preserves_last_phase_and_diagnostic() -> None:
    conn, launch, job = _claimed_launch("progress-before-expiry")
    report_relay_job(
        conn,
        actor_id=1,
        relay_id=RELAY_ID,
        job_kind="launch",
        job_id=launch.launch_id,
        lease_id=job.lease_id,
        result_code="progress",
        adapter_revision="codex-relay-v4",
        evidence={
            "result_code": "transport_exception",
            "native_launch_phase": "spawn",
            "native_diagnostic_ref": DIAGNOSTIC_REF,
        },
        now="2026-08-22T12:00:20Z",
    )

    assert settle_expired_relay_leases(conn, now="2026-08-22T12:06:01Z") == 1

    attempt, evidence = _attempt(conn, launch.launch_id)
    assert tuple(attempt[:2]) == (
        "2026-08-22T12:06:01Z",
        "relay_lease_expired",
    )
    assert evidence == {
        "native_diagnostic_command": f"yoke relay diagnostic {DIAGNOSTIC_REF}",
        "native_diagnostic_ref": DIAGNOSTIC_REF,
        "native_launch_phase": "spawn",
        "result_code": "relay_lease_expired",
    }
    launch_row = conn.execute(
        "SELECT state,result_code,result_evidence FROM session_launches "
        "WHERE launch_id=?",
        (launch.launch_id,),
    ).fetchone()
    assert tuple(launch_row[:2]) == ("outcome_unknown", "relay_lease_expired")
    assert json.loads(launch_row[2]) == evidence


def test_uncertain_adapter_result_surfaces_its_specific_terminal_code() -> None:
    conn, launch, job = _claimed_launch("specific-terminal-code")

    result = report_relay_job(
        conn,
        actor_id=1,
        relay_id=RELAY_ID,
        job_kind="launch",
        job_id=launch.launch_id,
        lease_id=job.lease_id,
        result_code="outcome_unknown",
        adapter_revision="codex-relay-v4",
        evidence={
            "result_code": "identity_uncorrelated",
            "native_launch_phase": "thread_identity",
        },
        now="2026-08-22T12:00:20Z",
    )

    assert result["state"] == "outcome_unknown"
    assert result["result_code"] == "identity_uncorrelated"
    attempt, evidence = _attempt(conn, launch.launch_id)
    assert attempt[1] == "outcome_unknown"
    assert evidence["native_launch_phase"] == "thread_identity"


def test_late_report_enriches_expired_attempt_without_hiding_expiry() -> None:
    conn, launch, job = _claimed_launch("late-report-evidence")
    settle_expired_relay_leases(conn, now="2026-08-22T12:06:01Z")

    result = report_relay_job(
        conn,
        actor_id=1,
        relay_id=RELAY_ID,
        job_kind="launch",
        job_id=launch.launch_id,
        lease_id=job.lease_id,
        result_code="outcome_unknown",
        adapter_revision="codex-relay-v4",
        evidence={
            "result_code": "transport_exception",
            "native_launch_phase": "spawn",
            "native_diagnostic_ref": DIAGNOSTIC_REF,
        },
        now="2026-08-22T12:06:10Z",
    )

    assert result == {
        "launch_id": launch.launch_id,
        "state": "outcome_unknown",
        "result_code": "relay_lease_expired",
    }
    attempt, evidence = _attempt(conn, launch.launch_id)
    assert attempt[1] == "relay_lease_expired"
    assert evidence["result_code"] == "relay_lease_expired"
    assert evidence["native_launch_phase"] == "spawn"
    assert evidence["native_diagnostic_ref"] == DIAGNOSTIC_REF


def test_successful_launch_state_and_result_remain_unchanged() -> None:
    conn, launch, job = _claimed_launch("successful-launch")

    result = report_relay_job(
        conn,
        actor_id=1,
        relay_id=RELAY_ID,
        job_kind="launch",
        job_id=launch.launch_id,
        lease_id=job.lease_id,
        result_code="native_created",
        native_session_id="native-session",
        adapter_revision="codex-relay-v4",
        evidence={
            "result_code": "accepted",
            "native_launch_phase": "native_running",
        },
        now="2026-08-22T12:00:20Z",
    )

    assert result["state"] == "awaiting_registration"
    assert result["result_code"] == "native_created"
