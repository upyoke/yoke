"""Unexpected health-check crashes record as ``HC-internal-error``."""

from __future__ import annotations

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
