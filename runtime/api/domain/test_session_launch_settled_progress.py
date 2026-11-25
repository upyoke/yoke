"""A finished launch retains its own outcome when relay progress arrives."""

import json

from runtime.api.domain.session_launch_test_support import (
    NOW,
    add_relay,
    assigned_launch,
    relay_connection,
)
from yoke_core.domain.session_launch_store import get_launch, update_launch
from yoke_core.domain.session_relay import claim_relay_job, report_relay_job
from yoke_core.domain.session_relay_expiry import settle_expired_relay_leases
from yoke_core.domain.session_relay_types import RelayHeartbeat


def test_progress_preserves_exit_and_current_result_after_success():
    machine = "11111111-1111-4111-8111-111111111111"
    relay = f"machine:{machine}"
    conn = relay_connection()
    add_relay(conn, relay_id=relay, machine_id=machine)
    launch = assigned_launch(conn, key="progress-after-success", machine_id=machine)
    heartbeat = RelayHeartbeat(
        relay_id=relay, actor_id=1, machine_id=machine, hostname="relay-host",
        relay_version="0.1.1", surface_versions={"codex-cli": "0.148.0a15"},
        project_ids=(10,),
    )
    job, = claim_relay_job(conn, heartbeat, wait_seconds=0, now_provider=lambda: NOW).jobs
    settle_expired_relay_leases(conn, now="2026-08-22T12:06:01.000000Z")
    evidence = {
        "native_exit_at": "2026-08-22T12:06:02.000000Z",
        "previous_launch_result": "relay_lease_expired",
    }
    update_launch(
        conn, launch.launch_id, state="succeeded", result_code="registered_and_acknowledged",
        native_launch_phase="native_exited", result_evidence=json.dumps(evidence),
    )
    conn.commit()

    report_relay_job(
        conn, actor_id=1, relay_id=relay, job_kind="launch", job_id=launch.launch_id,
        lease_id=job.lease_id, result_code="progress", adapter_revision="relay-v4",
        evidence={"native_launch_phase": "spawn"}, now="2026-08-22T12:06:03.000000Z",
    )

    stored = get_launch(conn, launch.launch_id)
    assert stored.state == "succeeded"
    assert stored.result_code == "registered_and_acknowledged"
    assert stored.native_launch_phase == "native_exited"
    assert json.loads(stored.result_evidence) == evidence
