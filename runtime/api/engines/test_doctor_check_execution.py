"""Unexpected health-check crashes record as ``HC-internal-error``."""

from __future__ import annotations

from yoke_contracts.control_plane_locality import (
    refuse_direct_connection,
    remote_control_plane,
)
from yoke_core.engines.doctor_check_execution import (
    INTERNAL_ERROR_CHECK_ID,
    execute_check_isolated,
)
from yoke_core.engines.doctor_registry_types import HealthCheck
from yoke_core.engines.doctor_report import DoctorArgs, RecordCollector


def test_unexpected_crash_is_named_internal_error() -> None:
    def _boom(_conn, _args, _rec):
        raise RuntimeError("probe exploded")

    rec = RecordCollector()
    execute_check_isolated(
        object(),
        DoctorArgs(quick=True, project="yoke"),
        rec,
        HealthCheck("session-relay", "Machine relay", _boom),
    )
    assert len(rec.results) == 1
    row = rec.results[0]
    assert row.check_id == INTERNAL_ERROR_CHECK_ID
    assert row.result == "FAIL"
    assert "session-relay" in row.detail
    assert "probe exploded" in row.detail


def test_control_plane_refusal_is_actionable_and_does_not_stop_roster() -> None:
    def _refuse(_conn, _args, _rec):
        refuse_direct_connection("test status lookup")

    def _pass(_conn, _args, rec):
        rec.record("HC-after-refusal", "After refusal", "PASS", "")

    rec = RecordCollector()
    args = DoctorArgs(quick=True, project="yoke")
    with remote_control_plane():
        execute_check_isolated(
            object(),
            args,
            rec,
            HealthCheck("status-lookup", "Status lookup", _refuse),
        )
    execute_check_isolated(
        object(),
        args,
        rec,
        HealthCheck("after-refusal", "After refusal", _pass),
    )

    assert [row.result for row in rec.results] == ["FAIL", "PASS"]
    refusal = rec.results[0]
    assert refusal.check_id == INTERNAL_ERROR_CHECK_ID
    assert "status-lookup" in refusal.detail
    assert "RemoteControlPlaneConnectionError" in refusal.detail
    assert "registered function-call read" in refusal.detail
    assert "local_authority_exempt" in refusal.detail
