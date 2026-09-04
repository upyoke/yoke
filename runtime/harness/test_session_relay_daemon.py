"""The standing relay outlives polls and follows the environment release."""

from __future__ import annotations

import logging
import signal
import threading
import time

import pytest

from yoke_harness.session_relay import ServeOnceJobOutcome, ServeOnceOutcome
from yoke_harness.session_relay_daemon import serve_forever


def _cycle_returning(state: str = "active"):
    def cycle(**_kwargs) -> ServeOnceOutcome:
        return ServeOnceOutcome(state, 1)

    return cycle


def test_leased_job_survives_the_poll_cycle_that_leased_it(tmp_path) -> None:
    """A job settles even though several cycles roll past it.

    This is the whole reason the relay stands: a respawned one-shot ends
    the job's lifetime with its own, so a launch that outlives the spawn
    settles as a lost lease.
    """
    release = threading.Event()
    settled: list[str] = []
    cycles: list[int] = []

    def slow_job() -> str:
        release.wait(5)
        settled.append("launch")
        return "launch"

    def cycle(*, state_dir=None, dispatch_job=None, **_kwargs) -> ServeOnceOutcome:
        cycles.append(1)
        if len(cycles) == 1:
            dispatch_job(slow_job)
        if len(cycles) == 3:
            release.set()
        return ServeOnceOutcome("dispatched", 1)

    outcome = serve_forever(
        state_dir=tmp_path,
        cycle=cycle,
        stop_after_cycles=3,
        idle_tick_seconds=0.01,
        install_signals=False,
    )

    assert settled == ["launch"]
    assert outcome.cycles == 3
    assert outcome.jobs_settled == 1


def test_termination_finishes_in_flight_work_before_returning(tmp_path) -> None:
    finished: list[str] = []
    started = threading.Event()

    def job() -> None:
        started.wait(5)
        time.sleep(0.05)
        finished.append("wake")

    def cycle(*, state_dir=None, dispatch_job=None, **_kwargs) -> ServeOnceOutcome:
        dispatch_job(job)
        started.set()
        signal.raise_signal(signal.SIGTERM)
        return ServeOnceOutcome("dispatched", 1)

    outcome = serve_forever(
        state_dir=tmp_path,
        cycle=cycle,
        idle_tick_seconds=0.01,
        install_signals=True,
    )

    assert finished == ["wake"]
    assert outcome.reason == "signal:SIGTERM"


def test_a_second_relay_on_the_machine_declines_the_lock(tmp_path) -> None:
    held = threading.Event()
    release = threading.Event()
    second: list[str] = []

    def holding_cycle(**_kwargs) -> ServeOnceOutcome:
        held.set()
        release.wait(5)
        return ServeOnceOutcome("active", 1)

    def first() -> None:
        serve_forever(
            state_dir=tmp_path,
            cycle=holding_cycle,
            stop_after_cycles=1,
            idle_tick_seconds=0.01,
            install_signals=False,
        )

    thread = threading.Thread(target=first)
    thread.start()
    try:
        assert held.wait(5)
        outcome = serve_forever(
            state_dir=tmp_path,
            cycle=_cycle_returning(),
            stop_after_cycles=1,
            idle_tick_seconds=0.01,
            install_signals=False,
        )
        second.append(outcome.reason)
    finally:
        release.set()
        thread.join(5)

    assert second == ["locked"]


@pytest.mark.parametrize("cap", (1, 2, 4))
def test_cycle_cap_bounds_a_directly_driven_loop(tmp_path, cap: int) -> None:
    outcome = serve_forever(
        state_dir=tmp_path,
        cycle=_cycle_returning(),
        stop_after_cycles=cap,
        idle_tick_seconds=0.001,
        install_signals=False,
    )

    assert outcome.cycles == cap
    assert outcome.reason == "cycle_cap"
    assert outcome.last_state == "active"


def test_failure_burst_logs_first_periodic_and_recovery_lines(caplog) -> None:
    import yoke_harness.session_relay_failure_log as failure_log

    interval = failure_log.FAILURE_LOG_INTERVAL_SECONDS
    observed = iter((0.0, 10.0, float(interval), float(interval + 5)))
    reporter = failure_log.FailureReporter(
        interval_seconds=interval,
        clock=lambda: next(observed),
    )
    caplog.set_level(logging.WARNING, logger=failure_log.__name__)

    reporter.failed("poll", "request rejected")
    reporter.failed("poll", "request rejected")
    reporter.failed("poll", "request rejected")
    reporter.recovered("poll")

    messages = [record.getMessage() for record in caplog.records]
    assert messages == [
        "relay poll failed: request rejected; consecutive_failures=1 "
        "elapsed_seconds=0.0",
        "relay poll failed: request rejected; consecutive_failures=3 "
        f"elapsed_seconds={interval:.1f}",
        "relay poll recovered; consecutive_failures=3 "
        f"elapsed_seconds={interval + 5:.1f}",
    ]


def test_claim_failure_logs_reason_then_poll_recovery(tmp_path, caplog) -> None:
    outcomes = iter(
        (
            ServeOnceOutcome("claim_failed", error_code="unexpected_field"),
            ServeOnceOutcome("active", 1),
        )
    )
    caplog.set_level(logging.WARNING, logger="yoke_harness.session_relay_failure_log")

    serve_forever(
        state_dir=tmp_path,
        cycle=lambda **_kwargs: next(outcomes),
        stop_after_cycles=2,
        idle_tick_seconds=0,
        install_signals=False,
    )

    messages = [record.getMessage() for record in caplog.records]
    assert any("relay poll failed: unexpected_field" in line for line in messages)
    assert any(
        "relay poll recovered; consecutive_failures=1" in line for line in messages
    )


def test_poll_exception_is_logged_without_ending_the_relay(tmp_path, caplog) -> None:
    calls: list[int] = []

    def cycle(**_kwargs) -> ServeOnceOutcome:
        calls.append(1)
        if len(calls) == 1:
            raise ValueError("server rejected relay payload")
        return ServeOnceOutcome("active", 1)

    caplog.set_level(logging.WARNING, logger="yoke_harness.session_relay_failure_log")
    outcome = serve_forever(
        state_dir=tmp_path,
        cycle=cycle,
        stop_after_cycles=2,
        idle_tick_seconds=0,
        install_signals=False,
    )

    messages = [record.getMessage() for record in caplog.records]
    assert outcome.cycles == 2
    assert any(
        "relay poll failed: ValueError: server rejected" in line for line in messages
    )
    assert any(
        "relay poll recovered; consecutive_failures=1" in line for line in messages
    )


def test_async_report_failure_is_logged_with_its_error_code(tmp_path, caplog) -> None:
    def cycle(*, dispatch_job=None, **_kwargs) -> ServeOnceOutcome:
        dispatch_job(
            lambda: ServeOnceJobOutcome(
                "report_failed",
                error_code="report_contract_rejected",
            )
        )
        return ServeOnceOutcome("dispatched", 1)

    caplog.set_level(logging.WARNING, logger="yoke_harness.session_relay_failure_log")
    serve_forever(
        state_dir=tmp_path,
        cycle=cycle,
        stop_after_cycles=1,
        idle_tick_seconds=0,
        install_signals=False,
    )

    messages = [record.getMessage() for record in caplog.records]
    assert any(
        "relay report failed: report_contract_rejected" in record.getMessage()
        for record in caplog.records
    )
    assert not any("relay report recovered" in line for line in messages)


def test_async_settlement_exception_logs_the_operation_and_exception(
    tmp_path, caplog
) -> None:
    def fail_settlement() -> None:
        raise RuntimeError("checkpoint response was rejected")

    def cycle(*, dispatch_job=None, **_kwargs) -> ServeOnceOutcome:
        dispatch_job(fail_settlement)
        return ServeOnceOutcome("dispatched", 1)

    caplog.set_level(logging.WARNING, logger="yoke_harness.session_relay_failure_log")
    serve_forever(
        state_dir=tmp_path,
        cycle=cycle,
        stop_after_cycles=1,
        idle_tick_seconds=0,
        install_signals=False,
    )

    assert any(
        "relay job settlement failed: RuntimeError: checkpoint response was rejected"
        in record.getMessage()
        for record in caplog.records
    )
