"""Server-side leasing and settlement for termination reap jobs."""

from __future__ import annotations

import json

from runtime.api.domain.session_launch_test_support import (
    NOW,
    add_relay,
    relay_connection,
)
from yoke_core.domain.session_relay import claim_relay_job, report_relay_job
from yoke_core.domain.session_relay_types import RelayHeartbeat


MACHINE_ID = "11111111-1111-4111-8111-111111111111"
RELAY_ID = f"machine:{MACHINE_ID}"
TARGET_SESSION_ID = "22222222-2222-4222-8222-222222222222"
NATIVE_ID = "33333333-3333-4333-8333-333333333333"


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


def _connection():
    conn = relay_connection()
    add_relay(
        conn,
        relay_id=RELAY_ID,
        machine_id=MACHINE_ID,
    )
    conn.execute(
        "INSERT INTO harness_sessions "
        "(session_id,project_id,executor_surface,executor_version,machine_id,"
        "model,executor,execution_lane,last_heartbeat,offered_at,ended_at,"
        "terminated_at) VALUES (?,?,?,?,?,?,'codex','direct',?,?,?,?)",
        (
            TARGET_SESSION_ID,
            10,
            "codex-cli",
            "0.148.0a15",
            MACHINE_ID,
            "gpt-5",
            NOW,
            NOW,
            NOW,
            NOW,
        ),
    )
    conn.execute(
        "INSERT INTO session_termination_reaps "
        "(target_session_id,project_id,machine_id,executor_surface,"
        "target_native_thread_id,state,requested_at) "
        "VALUES (?,?,?,?,?,'pending',?)",
        (TARGET_SESSION_ID, 10, MACHINE_ID, "codex-cli", NATIVE_ID, NOW),
    )
    conn.commit()
    return conn


def test_relay_prioritizes_and_settles_termination_reap() -> None:
    conn = _connection()

    claimed = claim_relay_job(
        conn,
        _heartbeat(),
        wait_seconds=0,
        now_provider=lambda: NOW,
    )

    assert len(claimed.jobs) == 1
    job = claimed.jobs[0]
    assert job.job_kind == "terminate"
    assert job.job_id == TARGET_SESSION_ID
    assert job.target_session_id == TARGET_SESSION_ID
    assert job.target_native_thread_id == NATIVE_ID
    # The kill already landed, so the target's derived liveness is ended;
    # there is no `terminated` liveness value.
    assert job.target_liveness == "ended"
    assert job.native_instruction == ""

    result = report_relay_job(
        conn,
        actor_id=1,
        relay_id=RELAY_ID,
        job_kind="terminate",
        job_id=job.job_id,
        lease_id=job.lease_id,
        result_code="killed",
        adapter_revision="termination-adapter-1",
        evidence={"duration_ms": 7, "stderr": "must not persist"},
        now="2026-08-22T12:00:07Z",
    )

    assert result == {
        "target_session_id": TARGET_SESSION_ID,
        "result_code": "killed",
    }
    row = conn.execute(
        "SELECT state,result_code,evidence FROM session_termination_reaps"
    ).fetchone()
    assert row["state"] == "succeeded"
    assert row["result_code"] == "killed"
    assert json.loads(row["evidence"]) == {
        "adapter_revision": "termination-adapter-1",
        "duration_ms": 7,
    }


def test_unreachable_machine_stays_pending_for_its_own_relay() -> None:
    conn = _connection()
    other = RelayHeartbeat(
        relay_id="machine:44444444-4444-4444-8444-444444444444",
        actor_id=1,
        machine_id="44444444-4444-4444-8444-444444444444",
        hostname="other-relay",
        relay_version="0.1.1",
        surface_versions={"codex-cli": "0.148.0a15"},
        project_ids=(10,),
    )

    claimed = claim_relay_job(
        conn,
        other,
        wait_seconds=0,
        now_provider=lambda: NOW,
    )

    assert claimed.jobs == ()
    assert (
        conn.execute("SELECT state FROM session_termination_reaps").fetchone()[0]
        == "pending"
    )
