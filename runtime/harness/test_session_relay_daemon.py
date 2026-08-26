"""The standing relay outlives its poll cycles, its signals, and its source."""

from __future__ import annotations

import signal
import threading
import time

import pytest

from yoke_harness.session_relay import ServeOnceOutcome
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


def test_source_change_replaces_the_process_rather_than_stopping(
    tmp_path, monkeypatch
) -> None:
    """A relay that stops serving is a machine whose wakes stop landing."""
    import yoke_harness.session_relay_daemon as daemon

    reloaded: list[object] = []
    monkeypatch.setattr(daemon, "source_fingerprint", lambda roots=None: "before")
    monkeypatch.setattr(daemon, "source_changed", lambda previous, roots=None: True)

    outcome = serve_forever(
        state_dir=tmp_path,
        cycle=_cycle_returning(),
        idle_tick_seconds=0.01,
        source_check_interval_seconds=0,
        install_signals=False,
        reload_exec=lambda argv=None, **_kw: reloaded.append(argv),
    )

    assert outcome.reason == "source_changed"
    assert outcome.cycles == 1
    assert reloaded == [None]


def test_source_is_not_re_fingerprinted_on_every_tick(tmp_path, monkeypatch) -> None:
    """Stat-walking every module per tick is the burn this daemon removes."""
    import yoke_harness.session_relay_daemon as daemon

    checks: list[str] = []
    monkeypatch.setattr(daemon, "source_fingerprint", lambda roots=None: "steady")
    monkeypatch.setattr(
        daemon,
        "source_changed",
        lambda previous, roots=None: bool(checks.append(previous)) or False,
    )

    outcome = serve_forever(
        state_dir=tmp_path,
        cycle=_cycle_returning(),
        stop_after_cycles=5,
        idle_tick_seconds=0.001,
        source_check_interval_seconds=3600,
        install_signals=False,
    )

    assert outcome.cycles == 5
    assert checks == []


def test_unchanged_source_keeps_serving_without_reloading(
    tmp_path, monkeypatch
) -> None:
    import yoke_harness.session_relay_daemon as daemon

    reloaded: list[object] = []
    monkeypatch.setattr(daemon, "source_fingerprint", lambda roots=None: "steady")
    monkeypatch.setattr(daemon, "source_changed", lambda previous, roots=None: False)

    outcome = serve_forever(
        state_dir=tmp_path,
        cycle=_cycle_returning(),
        stop_after_cycles=2,
        idle_tick_seconds=0.001,
        source_check_interval_seconds=0,
        install_signals=False,
        reload_exec=lambda argv=None, **_kw: reloaded.append(argv),
    )

    assert outcome.reason == "cycle_cap"
    assert reloaded == []


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
