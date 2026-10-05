"""Parallel Doctor reads preserve ordering and share the parent's deadline."""

import time

import pytest

from yoke_contracts import doctor_budget
from yoke_core.engines.doctor_parallel_reads import bounded_read_map


def test_reads_keep_input_order_and_inherit_remaining_budget(monkeypatch):
    monkeypatch.setattr(doctor_budget, "CHECK_BUDGET_S", 0.1)

    def read(value):
        time.sleep(0.002 * (4 - value))
        return value, doctor_budget.remaining_seconds(100)

    with doctor_budget.check_budget():
        rows = list(bounded_read_map(read, range(4)))
    assert [value for value, _ in rows] == list(range(4))
    assert all(0 < remaining <= 0.1 for _, remaining in rows)


def test_read_deadline_does_not_wait_for_other_pending_reads(monkeypatch):
    monkeypatch.setattr(doctor_budget, "CHECK_BUDGET_S", 0.02)
    started = time.monotonic()
    with (
        pytest.raises(doctor_budget.DoctorBudgetExhausted),
        doctor_budget.check_budget(),
    ):
        list(bounded_read_map(lambda _: time.sleep(0.2), range(20)))
    assert time.monotonic() - started < 0.15
