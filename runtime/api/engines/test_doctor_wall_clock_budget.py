"""Every check has a deadline, enforced at boundaries rather than mid-call."""

from __future__ import annotations

import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor

import pytest

from yoke_contracts import doctor_budget
from yoke_core.engines.doctor_check_execution import execute_check_isolated
from yoke_core.engines.doctor_registry_types import HealthCheck
from yoke_core.engines.doctor_report import DoctorArgs, RecordCollector


@pytest.mark.parametrize("worker_thread", [False, True])
def test_overrunning_check_is_incomplete_without_tracing_it(monkeypatch, worker_thread):
    monkeypatch.setattr(doctor_budget, "CHECK_BUDGET_S", 0.02)
    traces = []

    def slow(conn, args, rec):
        traces.append(sys.gettrace())
        rec.record("HC-partial", "Partial", "PASS", "")
        time.sleep(0.05)
        rec.record("HC-finished", "Finished", "PASS", "")

    def run():
        previous = sys.gettrace()
        rec = RecordCollector()
        execute_check_isolated(
            object(), DoctorArgs(), rec, HealthCheck("python-loop", "Python loop", slow)
        )
        assert traces == [previous]
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


def test_paused_removal_does_not_spend_the_check_budget(monkeypatch):
    """A removal that outlasts the check keeps the seconds left for verdicts."""
    monkeypatch.setattr(doctor_budget, "CHECK_BUDGET_S", 0.2)
    left = None
    with doctor_budget.check_budget():
        with doctor_budget.pause_check_budget():
            time.sleep(0.5)
        left = doctor_budget.remaining_budget()
    assert left is not None and left > 0.05


def test_running_subprocess_finishes_before_the_budget_is_enforced(monkeypatch):
    monkeypatch.setattr(doctor_budget, "CHECK_BUDGET_S", 0.02)
    finished = []

    def check(conn, args, rec):
        subprocess.run(
            [sys.executable, "-c", "import time; time.sleep(0.1)"], check=True
        )
        finished.append(True)

    rec = RecordCollector()
    execute_check_isolated(
        object(), DoctorArgs(), rec, HealthCheck("subprocess", "Subprocess", check)
    )
    assert finished == [True]
    assert rec.results[0].check_id == "HC-check-incomplete"


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
