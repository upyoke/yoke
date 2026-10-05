"""Every check has a deadline, including CPU-only and project-local checks."""

from __future__ import annotations

import sys
import time
from concurrent.futures import ThreadPoolExecutor

import pytest

from yoke_contracts import doctor_budget
from yoke_core.engines.doctor_check_execution import execute_check_isolated
from yoke_core.engines.doctor_registry_types import HealthCheck
from yoke_core.engines.doctor_report import DoctorArgs, RecordCollector


@pytest.mark.parametrize("worker_thread", [False, True])
def test_pure_python_check_cannot_run_past_its_budget(monkeypatch, worker_thread):
    monkeypatch.setattr(doctor_budget, "CHECK_BUDGET_S", 0.02)

    def slow(conn, args, rec):
        rec.record("HC-partial", "Partial", "PASS", "")
        try:
            while True:
                pass
        except Exception:
            rec.record("HC-swallowed", "Swallowed", "PASS", "")

    def run():
        previous = sys.gettrace()
        rec = RecordCollector()
        started = time.monotonic()
        execute_check_isolated(
            object(), DoctorArgs(), rec, HealthCheck("python-loop", "Python loop", slow)
        )
        assert time.monotonic() - started < 1
        assert sys.gettrace() is previous
        assert len(rec.results) == 1
        row = rec.results[0]
        assert row.check_id == "HC-check-incomplete"
        assert row.result == "FAIL"
        assert "python-loop" in row.detail
        assert "Recovery:" in row.detail

    if worker_thread:
        with ThreadPoolExecutor(max_workers=1) as executor:
            executor.submit(run).result(timeout=2)
    else:
        run()


def test_postgres_connection_without_autocommit_refuses_before_query():
    class Connection:
        def execute(self, *args):
            raise AssertionError("unbounded SQL was executed")

        def cursor(self, *args):
            raise AssertionError("unbounded cursor was opened")

    def check(conn, args, rec):
        raise AssertionError("the unbounded connection reached the check")

    rec = RecordCollector()
    execute_check_isolated(
        Connection(), DoctorArgs(), rec, HealthCheck("database", "Database", check)
    )
    assert len(rec.results) == 1
    assert rec.results[0].result == "FAIL"
    assert "doctor_postgres_autocommit_unavailable" in rec.results[0].detail
    assert "Recovery:" in rec.results[0].detail
