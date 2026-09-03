"""Launch progress, expiry evidence, and terminal result-code tests."""

from __future__ import annotations

import json

import pytest

from yoke_core.domain.session_launch_execution import reconcile_launch
from yoke_core.domain.session_launch_deadlines import settle_launch_deadlines
from yoke_core.domain.session_launch_requests import retry_launch
from yoke_core.domain.session_launch_store import get_launch
from yoke_core.domain.session_launch_types import SessionLaunchError
from yoke_core.domain.session_relay import claim_relay_job, report_relay_job
from yoke_core.domain.session_relay_expiry import settle_expired_relay_leases
from yoke_core.domain.session_relay_types import RelayHeartbeat
from runtime.api.domain.session_launch_test_support import (
    NOW,
    add_relay,
    assigned_launch,
    authorization,
    relay_connection,
)


MACHINE_ID = "11111111-1111-4111-8111-111111111111"
RELAY_ID = f"machine:{MACHINE_ID}"
DIAGNOSTIC_REF = "nd-aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"


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
    # The relay's own last word survives the closure. The document also
    # carries what the server observed as it closed the attempt, so this
    # asserts the preserved keys rather than the absence of every other one.
    assert (
        evidence.items()
        >= {
            "native_diagnostic_command": f"yoke relay diagnostic {DIAGNOSTIC_REF}",
            "native_diagnostic_ref": DIAGNOSTIC_REF,
            "native_launch_phase": "spawn",
            "result_code": "relay_lease_expired",
        }.items()
    )
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


def test_live_slow_spawn_is_durable_and_retry_reattaches() -> None:
    conn, launch, job = _claimed_launch("live-slow-spawn")
    report_relay_job(
        conn,
        actor_id=1,
        relay_id=RELAY_ID,
        job_kind="launch",
        job_id=launch.launch_id,
        lease_id=job.lease_id,
        result_code="progress",
        adapter_revision="claude-native-v6",
        evidence={
            "result_code": "native_spawn_pending",
            "native_launch_phase": "spawn_alive",
            "native_launch_pid": 4242,
            "duration_ms": 180_000,
        },
        now="2026-08-22T12:03:00Z",
    )

    observed = get_launch(conn, launch.launch_id)
    deadline = observed.deadline_at
    assert observed.native_launch_pid == 4242
    assert observed.native_launch_phase == "spawn_alive"
    assert observed.native_launch_observed_at == "2026-08-22T12:03:00Z"
    assert observed.spawn_duration_ms == 180_000

    attached = retry_launch(
        conn,
        launch_id=launch.launch_id,
        auth=authorization(),
        now="2026-08-22T12:03:01Z",
    )
    assert attached.state == "launching"
    assert attached.result_code == "native_spawn_pending"
    assert attached.deadline_at == deadline
    assert (
        conn.execute(
            "SELECT COUNT(*) FROM session_launch_attempts WHERE launch_id=?",
            (launch.launch_id,),
        ).fetchone()[0]
        == 1
    )

    with pytest.raises(SessionLaunchError) as refused:
        reconcile_launch(
            conn,
            launch_id=launch.launch_id,
            auth=authorization(),
            observed_native_id=None,
            now="2026-08-22T12:03:02Z",
        )
    assert refused.value.code == "native_process_alive"
    assert "4242" in str(refused.value)

    conn.execute(
        "UPDATE session_relays SET lease_expires_at=? WHERE relay_id=?",
        ("2026-08-22T12:03:05Z", RELAY_ID),
    )
    conn.commit()
    assert settle_expired_relay_leases(conn, now="2026-08-22T12:05:01Z") == 0
    assert (
        conn.execute(
            "SELECT completed_at FROM session_launch_attempts WHERE launch_id=?",
            (launch.launch_id,),
        ).fetchone()[0]
        is None
    )

    report_relay_job(
        conn,
        actor_id=1,
        relay_id=RELAY_ID,
        job_kind="launch",
        job_id=launch.launch_id,
        lease_id=job.lease_id,
        result_code="progress",
        adapter_revision="claude-native-v6",
        evidence={
            "native_launch_phase": "spawn_completed_after_bound",
            "native_launch_pid": 4242,
            "duration_ms": 190_000,
        },
        now="2026-08-22T12:05:02Z",
    )

    handoff = retry_launch(
        conn,
        launch_id=launch.launch_id,
        auth=authorization(),
        now="2026-08-22T12:05:02Z",
    )
    assert handoff.native_launch_phase == "spawn_completed_after_bound"
    assert (
        conn.execute(
            "SELECT COUNT(*) FROM session_launch_attempts WHERE launch_id=?",
            (launch.launch_id,),
        ).fetchone()[0]
        == 1
    )
    assert settle_expired_relay_leases(conn, now="2026-08-22T12:05:02Z") == 0
    assert settle_launch_deadlines(conn, now="2026-08-22T12:05:02Z") == []

    completed = report_relay_job(
        conn,
        actor_id=1,
        relay_id=RELAY_ID,
        job_kind="launch",
        job_id=launch.launch_id,
        lease_id=job.lease_id,
        result_code="native_created",
        native_session_id="native-session",
        adapter_revision="claude-native-v6",
        evidence={
            "result_code": "native_created",
            "native_launch_phase": "spawn_completed_after_bound",
            "native_launch_pid": 4242,
            "duration_ms": 190_000,
        },
        now="2026-08-22T12:05:03Z",
    )
    assert completed["state"] == "awaiting_registration"
    final = get_launch(conn, launch.launch_id)
    assert final.spawn_duration_ms == 190_000
    assert final.native_launch_phase == "spawn_completed_after_bound"
