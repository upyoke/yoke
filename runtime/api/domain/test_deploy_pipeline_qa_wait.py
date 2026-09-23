"""The deployment driver waits in-process for scoped QA, but only boundedly."""

from __future__ import annotations

from yoke_core.domain.deploy_pipeline_qa_wait import (
    AWAITING_SCOPED_QA,
    dispatch_until_qa_resolves,
)


class _Clock:
    def __init__(self) -> None:
        self.now = 0.0
        self.sleeps: list[float] = []

    def monotonic(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


def test_returns_an_immediate_non_waiting_result_without_sleeping() -> None:
    clock = _Clock()

    result = dispatch_until_qa_resolves(
        lambda: (0, "passed"),
        timeout_seconds=30,
        monotonic=clock.monotonic,
        sleep=clock.sleep,
    )

    assert result == (0, "passed")
    assert clock.sleeps == []


def test_repolls_until_scoped_qa_passes() -> None:
    clock = _Clock()
    outcomes = iter([(AWAITING_SCOPED_QA, "member pending")] * 2 + [(0, "accepted")])

    result = dispatch_until_qa_resolves(
        lambda: next(outcomes),
        timeout_seconds=30,
        poll_interval_seconds=15,
        monotonic=clock.monotonic,
        sleep=clock.sleep,
    )

    assert result == (0, "accepted")
    assert clock.sleeps == [15, 15]


def test_timeout_returns_the_wait_code_with_recovery() -> None:
    clock = _Clock()
    calls = 0

    def pending() -> tuple[int, str]:
        nonlocal calls
        calls += 1
        return AWAITING_SCOPED_QA, "member 42 has no passing run"

    result = dispatch_until_qa_resolves(
        pending,
        timeout_seconds=31,
        poll_interval_seconds=15,
        monotonic=clock.monotonic,
        sleep=clock.sleep,
    )

    assert result[0] == AWAITING_SCOPED_QA
    assert "timed out after 31s" in result[1]
    assert "re-drive this deployment run from the QA stage" in result[1]
    assert clock.sleeps == [15, 15, 1]
    assert calls == 4


def test_zero_timeout_performs_one_probe() -> None:
    clock = _Clock()
    calls = 0

    def pending() -> tuple[int, str]:
        nonlocal calls
        calls += 1
        return AWAITING_SCOPED_QA, "pending"

    result = dispatch_until_qa_resolves(
        pending,
        timeout_seconds=0,
        monotonic=clock.monotonic,
        sleep=clock.sleep,
    )

    assert result[0] == AWAITING_SCOPED_QA
    assert calls == 1
    assert clock.sleeps == []
