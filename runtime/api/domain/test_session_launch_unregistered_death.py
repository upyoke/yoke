"""A native gone before registration closes its launch on the reporting poll."""

from __future__ import annotations

import json

from yoke_contracts.session_control.launch_registration import (
    NATIVE_EXITED_UNREGISTERED_CODE,
)
from yoke_core.domain.session_launch_execution import (
    claim_assigned_launch,
    report_launch_attempt,
)
from yoke_core.domain.session_launch_store import get_launch
from yoke_core.domain.session_launch_unregistered_death import (
    CLOSURE_REASON,
    apply_unregistered_native_death_reports,
)
from runtime.api.domain.session_launch_test_support import (
    NOW,
    add_relay,
    assigned_launch,
    launch_connection,
)


DIAGNOSTIC_REF = "nd-11111111-1111-4111-8111-111111111111"
REFUSAL = "cursor-agent: authentication required"


def _awaiting_registration(conn, *, key: str = "unregistered-death"):
    """A launch whose native was created and has not registered a session."""
    launch = assigned_launch(conn, key=key)
    claim = claim_assigned_launch(
        conn,
        launch_id=launch.launch_id,
        relay_id="relay-1",
        machine_id="machine-1",
        now=NOW,
    )
    return report_launch_attempt(
        conn,
        launch_id=launch.launch_id,
        lease_id=claim.lease_id,
        result_code="native_created",
        native_session_id="native-session",
        now="2026-08-22T12:00:30Z",
    )


def _report(launch_id: str) -> dict[str, object]:
    return {
        "launch_id": launch_id,
        "evidence": {
            "native_pid": 4321,
            "exit_code": 1,
            "native_diagnostic_ref": DIAGNOSTIC_REF,
            "native_exit_at": "2026-08-22T12:00:41Z",
            "native_stderr_tail": REFUSAL,
        },
    }


def test_a_native_exit_without_registration_closes_the_launch_with_its_capture() -> (
    None
):
    conn = launch_connection()
    add_relay(conn)
    launch = _awaiting_registration(conn)
    assert launch.state == "awaiting_registration"

    outcome = apply_unregistered_native_death_reports(
        conn,
        machine_id="machine-1",
        authorized_projects=[10],
        reports=[_report(launch.launch_id)],
        now="2026-08-22T12:00:45Z",
    )

    assert outcome == {"closed_launches": [launch.launch_id], "skipped_launches": []}
    closed = get_launch(conn, launch.launch_id)
    # Closed now, rather than at a registration deadline ten minutes out.
    assert closed.state == "failed"
    assert closed.result_code == NATIVE_EXITED_UNREGISTERED_CODE
    assert closed.completed_at == "2026-08-22T12:00:45Z"
    evidence = json.loads(closed.result_evidence)
    assert evidence["closure_reason"] == CLOSURE_REASON
    assert evidence["exit_code"] == 1
    assert evidence["native_diagnostic_ref"] == DIAGNOSTIC_REF
    assert evidence["native_stderr_tail"] == REFUSAL
    assert evidence["launch_phase_reached"] == "awaiting_registration"
