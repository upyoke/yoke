"""Unexpected health-check crashes record as ``HC-internal-error``."""

from __future__ import annotations
import sys
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


def test_safe_point_exhaustion_discards_partial_verdicts(monkeypatch):
    monkeypatch.setattr(doctor_budget, "CHECK_BUDGET_S", 0.02)
    previous = sys.gettrace()

    def slow(conn, args, rec):
        rec.record("HC-early", "Early evidence", "PASS", "partial scan")
        try:
            while True:
                doctor_budget.remaining_seconds(doctor_budget.CHECK_BUDGET_S)
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
    assert [row.result for row in rec.results] == ["PASS", "FAIL"]
    assert "doctor_check_budget_exhausted" in rec.results[-1].detail
    assert "--only slow" in rec.results[-1].detail


def test_check_restores_the_callers_trace():
    previous = sys.gettrace()

    def check(conn, args, rec):
        assert sys.gettrace() is not previous
        rec.record("HC-trace", "Trace", "PASS", "")

    rec = RecordCollector()
    execute_check_isolated(
        object(), DoctorArgs(), rec, HealthCheck("trace", "Trace", check)
    )
    assert rec.results[0].result == "PASS"
    assert sys.gettrace() is previous


def test_non_database_connections_reach_the_check_unchanged():
    from yoke_core.engines.doctor_https_compose import UnavailableControlPlane

    class MinimalConnection:
        def execute(self, *_args):
            return self

    for native_conn in (MinimalConnection(), UnavailableControlPlane()):

        def check(conn, args, rec):
            assert conn is native_conn
            rec.record("HC-source", "Source check", "PASS", "")

        rec = RecordCollector()
        execute_check_isolated(
            native_conn, DoctorArgs(), rec, HealthCheck("source", "Source", check)
        )
        assert [row.check_id for row in rec.results] == ["HC-source"]
        assert rec.results[0].result == "PASS"


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


def test_postgres_budget_exhaustion_preserves_protocol_and_next_check(monkeypatch):
    from yoke_core.domain import db_backend

    monkeypatch.setattr(doctor_budget, "CHECK_BUDGET_S", 0.02)
    rec = RecordCollector()
    args = DoctorArgs()

    def blocked(conn, args, rec):
        conn.execute("SELECT pg_sleep(0.2)")

    def following(conn, args, rec):
        assert conn.execute("SELECT 1").fetchone()[0] == 1
        rec.record("HC-after-budget", "After budget", "PASS", "")

    with db_backend.connect() as conn:
        execute_check_isolated(
            conn, args, rec, HealthCheck("blocked", "Blocked", blocked)
        )
        execute_check_isolated(
            conn, args, rec, HealthCheck("following", "Following", following)
        )
    assert [row.check_id for row in rec.results] == [
        "HC-check-incomplete",
        "HC-after-budget",
    ]
    assert [row.result for row in rec.results] == ["FAIL", "PASS"]


def test_deadline_is_checked_after_active_postgres_protocol(monkeypatch):
    from yoke_core.domain import db_backend

    monkeypatch.setattr(doctor_budget, "CHECK_BUDGET_S", 0.02)
    rec = RecordCollector()
    with db_backend.connect() as conn:
        native_wait = conn.wait
        native_conn = conn

        def delayed_wait(gen, *args, **kwargs):
            def delay_protocol():
                ready = yield next(gen)
                time.sleep(0.03)
                for _ in range(1000):
                    pass
                while True:
                    try:
                        ready = yield gen.send(ready)
                    except StopIteration as stop:
                        return stop.value

            return native_wait(delay_protocol(), *args, **kwargs)

        def query(conn, args, rec):
            with monkeypatch.context() as patch:
                patch.setattr(native_conn, "wait", delayed_wait)
                conn.execute("SELECT pg_sleep(0.01)")

        execute_check_isolated(
            conn, DoctorArgs(), rec, HealthCheck("query", "Query", query)
        )
        assert conn.execute("SELECT 1").fetchone()[0] == 1
    assert rec.results[-1].check_id == "HC-check-incomplete"


def test_budget_recovery_failure_still_records_incomplete(monkeypatch):
    class Connection:
        calls = 0

        def rollback(self):
            self.calls += 1
            if self.calls > 1:
                raise RuntimeError("connection lost")

    def exhausted(conn, args, rec):
        raise doctor_budget.DoctorBudgetExhausted()

    rec = RecordCollector()
    execute_check_isolated(
        Connection(), DoctorArgs(), rec, HealthCheck("lost", "Lost", exhausted)
    )
    assert rec.results[-1].check_id == "HC-check-incomplete"
    assert "Transaction recovery failed: connection lost" in rec.results[-1].detail


def test_statement_timeout_escapes_best_effort_after_commit(monkeypatch):
    from yoke_core.domain import db_backend

    monkeypatch.setattr(doctor_budget, "CHECK_BUDGET_S", 0.02)

    def check(conn, args, rec):
        conn.execute("SELECT 1")
        conn.commit()
        try:
            with conn.cursor() as cursor:
                cursor.execute("SELECT pg_sleep(0.2)")
        except db_backend.database_error_types(conn):
            rec.record("HC-swallowed", "Swallowed", "PASS", "")

    rec = RecordCollector()
    with db_backend.connect() as conn:
        execute_check_isolated(
            conn, DoctorArgs(), rec, HealthCheck("query", "Query", check)
        )
        assert conn.execute("SHOW statement_timeout").fetchone()[0] == "0"
    assert len(rec.results) == 1
    assert rec.results[0].check_id == "HC-check-incomplete"


def test_autocommit_timeout_is_enforced_and_restored(monkeypatch):
    from yoke_core.domain import db_backend

    monkeypatch.setattr(doctor_budget, "CHECK_BUDGET_S", 0.02)
    rec = RecordCollector()
    with db_backend.connect() as conn:
        conn.autocommit = True
        conn.execute("SET statement_timeout='2s'")

        def check(conn, args, rec):
            conn.execute("SELECT pg_sleep(0.2)")

        execute_check_isolated(
            conn, DoctorArgs(), rec, HealthCheck("query", "Query", check)
        )
        assert conn.execute("SHOW statement_timeout").fetchone()[0] == "2s"
    assert rec.results[0].check_id == "HC-check-incomplete"
