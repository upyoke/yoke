"""Unexpected health-check crashes record as ``HC-internal-error``."""

from __future__ import annotations
import sys
import threading
import time

from yoke_contracts import doctor_budget

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


def test_cpu_check_exhaustion_retains_findings_and_never_passes(monkeypatch):
    monkeypatch.setattr(doctor_budget, "CHECK_BUDGET_S", 0.02)
    previous = sys.gettrace()

    def slow(conn, args, rec):
        rec.record("HC-early", "Early evidence", "PASS", "partial scan")
        try:
            while True:
                pass
        except Exception:
            rec.record("HC-swallowed", "Swallowed exception", "PASS", "")

    rec = RecordCollector()
    rec.record("HC-prior", "Earlier completed check", "PASS", "")
    started = time.monotonic()
    execute_check_isolated(
        object(), DoctorArgs(), rec, HealthCheck("slow", "Slow", slow)
    )
    assert time.monotonic() - started < 1
    assert sys.gettrace() is previous
    assert [row.result for row in rec.results] == ["PASS", "FAIL", "FAIL"]
    assert "doctor_check_budget_exhausted" in rec.results[-1].detail
    assert "--only slow" in rec.results[-1].detail


def test_database_wait_is_cancelled_and_roster_can_continue(monkeypatch):
    monkeypatch.setattr(doctor_budget, "CHECK_BUDGET_S", 0.02)
    released = threading.Event()

    class Connection:
        def cancel_safe(self, *, timeout):
            released.set()

        def rollback(self):
            pass

    def blocked(conn, args, rec):
        assert released.wait(1)
        rec.record("HC-late", "Late result", "PASS", "")

    rec = RecordCollector()
    execute_check_isolated(
        Connection(),
        DoctorArgs(),
        rec,
        HealthCheck("database-wait", "Database wait", blocked),
    )
    assert released.is_set()
    assert rec.fail_count >= 1
    assert rec.pass_count == 0
    assert "doctor_check_budget_exhausted" in rec.results[-1].detail


def test_http_and_subprocess_timeouts_share_check_deadline(monkeypatch):
    from yoke_cli.transport.response_deadline_read import deadline_after
    from yoke_core.engines import doctor_report

    monkeypatch.setattr(doctor_budget, "CHECK_BUDGET_S", 0.2)
    observed = []

    def run(*a, **k):
        observed.append(k["timeout"])

    monkeypatch.setattr(doctor_report.subprocess, "run", run)
    with doctor_budget.check_budget():
        assert deadline_after(30) - time.monotonic() < 0.2
        doctor_report._run(["probe"], timeout=30)
    assert 0 < observed[0] <= 0.2
