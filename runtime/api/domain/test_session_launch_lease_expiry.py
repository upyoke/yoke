"""An expired relay attempt leaves registration and delivery able to settle."""

import json
from datetime import timedelta

import pytest

from yoke_contracts.session_control.launch_registration import (
    LAUNCH_ADAPTER_STARTED_CODE,
    NATIVE_EXITED_UNREGISTERED_CODE,
)
from yoke_contracts.timestamps import parse_instant
from yoke_core.domain.session_launch_deadlines import settle_launch_deadlines
from yoke_core.domain.session_launch_execution import report_launch_attempt
from yoke_core.domain.session_launch_registration import (
    complete_launch_injection,
    prepare_launch_registration,
)
from yoke_core.domain.session_launch_store import get_launch
from yoke_core.domain.session_launch_types import (
    LAUNCH_LEASE_SECONDS,
    SessionLaunchError,
)
from yoke_core.domain.session_launch_unregistered_death import (
    apply_unregistered_native_death_reports,
)
from yoke_core.domain.session_message_receipts import acknowledge_message
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
SURFACE_VERSION = "0.148.0a15"
WORKER = "lease-expiry-worker"
LEASE_EXPIRED_AT = parse_instant(NOW) + timedelta(seconds=LAUNCH_LEASE_SECONDS + 1)
SETTLED_AT = LEASE_EXPIRED_AT + timedelta(seconds=1)


@pytest.fixture
def claimed_launch():
    conn = relay_connection()
    add_relay(conn, relay_id=RELAY_ID, machine_id=MACHINE_ID)
    launch = assigned_launch(conn, machine_id=MACHINE_ID)
    heartbeat = RelayHeartbeat(
        relay_id=RELAY_ID,
        actor_id=1,
        machine_id=MACHINE_ID,
        hostname="relay-host",
        relay_version="0.1.1",
        surface_versions={"codex-cli": SURFACE_VERSION},
        project_ids=(10,),
    )
    batch = claim_relay_job(conn, heartbeat, wait_seconds=0, now_provider=lambda: NOW)
    (job,) = batch.jobs
    return conn, launch.launch_id, job


@pytest.fixture
def awaiting_registration(claimed_launch):
    conn, launch_id, job = claimed_launch
    progress = report_relay_job(
        conn,
        actor_id=1,
        relay_id=RELAY_ID,
        job_kind="launch",
        job_id=launch_id,
        lease_id=job.lease_id,
        result_code="progress",
        adapter_revision="codex-relay-v4",
        evidence={
            "result_code": LAUNCH_ADAPTER_STARTED_CODE,
            "native_launch_phase": "adapter_start",
        },
        now="2026-08-22T12:00:10Z",
    )
    assert progress["state"] == "awaiting_registration"
    return claimed_launch


def _expire_attempt(conn, job):
    settle_expired_relay_leases(conn, now=LEASE_EXPIRED_AT)
    attempt = conn.execute(
        "SELECT completed_at, result_code, evidence FROM session_launch_attempts "
        "WHERE lease_id = ?",
        (job.lease_id,),
    ).fetchone()
    assert parse_instant(attempt["completed_at"]) == LEASE_EXPIRED_AT
    assert attempt["result_code"] == "relay_lease_expired"
    assert json.loads(attempt["evidence"])["closure_reason"] == "relay_lease_expiry"


def test_expired_attempt_keeps_unbound_launch_until_registration_deadline(
    awaiting_registration,
):
    conn, launch_id, job = awaiting_registration
    before = get_launch(conn, launch_id)

    _expire_attempt(conn, job)

    assert get_launch(conn, launch_id) == before
    with pytest.raises(SessionLaunchError) as late_report:
        report_launch_attempt(
            conn,
            launch_id=launch_id,
            lease_id=job.lease_id,
            result_code="native_created",
            native_session_id=WORKER,
            now=SETTLED_AT,
        )
    assert late_report.value.code == "report_conflict"
    report_relay_job(
        conn,
        actor_id=1,
        relay_id=RELAY_ID,
        job_kind="launch",
        job_id=launch_id,
        lease_id=job.lease_id,
        result_code="native_created",
        native_session_id=WORKER,
        adapter_revision="codex-relay-v4",
        evidence={"result_code": "accepted"},
        now=SETTLED_AT,
    )
    assert get_launch(conn, launch_id) == before
    (closed,) = settle_launch_deadlines(
        conn, launch_id=launch_id, now=before.deadline_at
    )
    assert (closed.state, closed.result_code) == ("failed", "registration_deadline")


def test_expired_attempt_keeps_bound_launch_open_for_acknowledgement(
    awaiting_registration,
):
    conn, launch_id, job = awaiting_registration
    conn.execute(
        "INSERT INTO harness_sessions (session_id, project_id, executor_surface, "
        "executor_version, machine_id, workspace, offered_at) "
        "VALUES (?, 10, 'codex-cli', ?, ?, '/project', ?)",
        (WORKER, SURFACE_VERSION, MACHINE_ID, NOW),
    )
    conn.commit()
    prepare_launch_registration(
        conn,
        launch_id=launch_id,
        attestation=job.launch_attestation,
        session_id=WORKER,
        now="2026-08-22T12:00:11Z",
    )
    injected = complete_launch_injection(
        conn,
        launch_id=launch_id,
        session_id=WORKER,
        injected=True,
        now="2026-08-22T12:00:12Z",
    )
    assert injected.result_code == "injected_awaiting_acknowledgement"

    _expire_attempt(conn, job)

    assert get_launch(conn, launch_id) == injected
    acknowledge_message(
        conn, message_id=injected.message_id, session_id=WORKER, now=SETTLED_AT
    )
    closed = get_launch(conn, launch_id)
    assert (closed.state, closed.result_code) == (
        "succeeded",
        "registered_and_acknowledged",
    )


def test_native_death_can_close_unbound_launch_after_attempt_expires(
    awaiting_registration,
):
    conn, launch_id, job = awaiting_registration
    _expire_attempt(conn, job)
    exit_at = "2026-08-22T12:05:02Z"

    outcome = apply_unregistered_native_death_reports(
        conn,
        machine_id=MACHINE_ID,
        authorized_projects=(10,),
        reports=[{"launch_id": launch_id, "evidence": {"native_exit_at": exit_at}}],
        now=SETTLED_AT,
    )

    assert outcome == {"closed_launches": [launch_id], "skipped_launches": []}
    closed = get_launch(conn, launch_id)
    assert (closed.state, closed.result_code) == (
        "failed",
        NATIVE_EXITED_UNREGISTERED_CODE,
    )
    evidence = json.loads(closed.result_evidence)
    assert evidence["closure_reason"] == "native_exited_before_registering"
    assert evidence["native_exit_at"] == exit_at


def test_expired_attempt_marks_launch_outcome_unknown_without_adapter_start(
    claimed_launch,
):
    conn, launch_id, job = claimed_launch
    assert get_launch(conn, launch_id).state == "launching"

    _expire_attempt(conn, job)

    closed = get_launch(conn, launch_id)
    assert (closed.state, closed.result_code) == (
        "outcome_unknown",
        "relay_lease_expired",
    )
