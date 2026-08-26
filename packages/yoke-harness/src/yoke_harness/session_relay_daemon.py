"""One standing relay process per machine: poll, supervise, reload, retire.

A relay that is respawned on a timer pays a fresh interpreter for every
poll and, worse, hands each job a lifetime no longer than the spawn that
leased it — a launch or wake whose process outlives its poll cycle dies
with it and settles as a lost lease. This module keeps one process alive
instead:

* the run lock is taken once, for the daemon's whole life, so a second
  relay on the machine cannot interleave between cycles of the first;
* leased jobs settle on a supervised worker pool whose lifetime is the
  job's, so the poll loop is never blocked behind one and a job finishes
  even though several cycles roll past it;
* because the loop is never blocked, its own claim keeps the machine's
  ``session_relays`` row and surface inventory continuously published —
  the state gap that appears while a long job holds a one-shot process;
* a termination signal and a source change both stop *starting* work and
  then wait for what is in flight, so neither drops a job on the floor.

A source change ends in ``exec`` rather than exit: a relay that stops
serving is a machine whose launches and wakes silently stop landing, so
replacing the process is the only honest response to new code.
"""

from __future__ import annotations

from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass, field
import logging
from pathlib import Path
import signal
import threading
import time
from typing import Callable, Sequence

from yoke_harness.session_relay import ServeOnceOutcome, run_serve_cycle
from yoke_harness.session_relay_schedule import relay_run_lock
from yoke_harness.session_relay_source_reload import (
    exec_reload,
    source_changed,
    source_fingerprint,
)


# How long the loop waits between cadence checks. The server owns the poll
# cadence; this only bounds how fast the daemon notices a stop request.
IDLE_TICK_SECONDS = 0.5

# Longest wait for in-flight jobs once the daemon has stopped starting new
# work. A native launch that has not settled by then is already supervised
# by its own attempt record, so waiting past this only delays the restart.
DRAIN_TIMEOUT_SECONDS = 120

# How often the serving source is re-fingerprinted. The check stats every
# module in the serving packages, so running it on every tick would spend
# thousands of syscalls a second to answer a question that changes only
# when someone deploys — the continuous burn this daemon exists to remove.
SOURCE_CHECK_INTERVAL_SECONDS = 30

_LOGGER = logging.getLogger(__name__)


@dataclass
class DaemonOutcome:
    """Why the daemon returned, and what it settled on the way out."""

    reason: str
    cycles: int = 0
    jobs_settled: int = 0
    last_state: str = ""


@dataclass
class _Supervisor:
    """Owns the worker pool and the futures still settling on it."""

    pool: ThreadPoolExecutor
    pending: list[Future] = field(default_factory=list)
    lock: threading.Lock = field(default_factory=threading.Lock)
    settled: int = 0

    def dispatch(self, settle: Callable[[], object]) -> None:
        future = self.pool.submit(self._guarded, settle)
        with self.lock:
            self.pending = [f for f in self.pending if not f.done()]
            self.pending.append(future)

    def _guarded(self, settle: Callable[[], object]) -> object:
        try:
            return settle()
        except Exception:  # noqa: BLE001 — one job must not stop the relay
            _LOGGER.warning("relay job settlement failed", exc_info=True)
            return None
        finally:
            with self.lock:
                self.settled += 1

    def drain(self, *, timeout: float) -> None:
        deadline = time.monotonic() + timeout
        while True:
            with self.lock:
                outstanding = [f for f in self.pending if not f.done()]
                self.pending = outstanding
            if not outstanding or time.monotonic() >= deadline:
                return
            time.sleep(IDLE_TICK_SECONDS)


class _StopRequest:
    """Records why the loop should stop starting new work."""

    def __init__(self) -> None:
        self._reason = ""
        self._event = threading.Event()

    def set(self, reason: str) -> None:
        if not self._reason:
            self._reason = reason
        self._event.set()

    @property
    def reason(self) -> str:
        return self._reason

    def is_set(self) -> bool:
        return self._event.is_set()

    def wait(self, seconds: float) -> None:
        self._event.wait(seconds)


def _install_signal_handlers(stop: _StopRequest) -> dict[int, object]:
    """Route termination signals into the stop request; return what they replaced."""

    def handle(signum: int, _frame: object) -> None:
        stop.set(f"signal:{signal.Signals(signum).name}")

    previous: dict[int, object] = {}
    for signum in (signal.SIGTERM, signal.SIGINT):
        try:
            previous[signum] = signal.signal(signum, handle)
        except ValueError:
            # Not the main thread — a caller driving the loop directly owns
            # its own stop signal, so this is not an error.
            _LOGGER.debug("relay daemon could not install %s handler", signum)
    return previous


def _restore_signal_handlers(previous: dict[int, object]) -> None:
    for signum, handler in previous.items():
        try:
            signal.signal(signum, handler)  # type: ignore[arg-type]
        except (ValueError, TypeError):
            _LOGGER.debug("relay daemon could not restore %s handler", signum)


def serve_forever(
    *,
    state_dir: Path | None = None,
    cycle: Callable[..., ServeOnceOutcome] = run_serve_cycle,
    stop_after_cycles: int | None = None,
    idle_tick_seconds: float = IDLE_TICK_SECONDS,
    drain_timeout_seconds: float = DRAIN_TIMEOUT_SECONDS,
    max_job_workers: int = 4,
    reload_argv: Sequence[str] | None = None,
    reload_exec: Callable[..., None] = exec_reload,
    source_check_interval_seconds: float = SOURCE_CHECK_INTERVAL_SECONDS,
    install_signals: bool = True,
    **cycle_kwargs: object,
) -> DaemonOutcome:
    """Serve this machine's relay until a signal, a source change, or a cap.

    ``stop_after_cycles`` bounds the loop for callers that drive it
    directly; the installed service leaves it unset and runs until the
    machine stops it.
    """
    stop = _StopRequest()
    prior_handlers = _install_signal_handlers(stop) if install_signals else {}
    try:
        return _serve_under_lock(
            stop,
            state_dir=state_dir,
            cycle=cycle,
            stop_after_cycles=stop_after_cycles,
            idle_tick_seconds=idle_tick_seconds,
            drain_timeout_seconds=drain_timeout_seconds,
            max_job_workers=max_job_workers,
            reload_argv=reload_argv,
            reload_exec=reload_exec,
            source_check_interval_seconds=source_check_interval_seconds,
            **cycle_kwargs,
        )
    finally:
        _restore_signal_handlers(prior_handlers)


def _serve_under_lock(
    stop: _StopRequest,
    *,
    state_dir: Path | None,
    cycle: Callable[..., ServeOnceOutcome],
    stop_after_cycles: int | None,
    idle_tick_seconds: float,
    drain_timeout_seconds: float,
    max_job_workers: int,
    reload_argv: Sequence[str] | None,
    reload_exec: Callable[..., None],
    source_check_interval_seconds: float,
    **cycle_kwargs: object,
) -> DaemonOutcome:
    """Hold the machine's relay lock for as long as this daemon serves."""
    with relay_run_lock(state_dir) as acquired:
        if not acquired:
            return DaemonOutcome("locked")
        baseline = source_fingerprint()
        supervisor = _Supervisor(ThreadPoolExecutor(max_workers=max_job_workers))
        cycles = 0
        last_state = ""
        next_source_check = time.monotonic() + source_check_interval_seconds
        try:
            while not stop.is_set():
                outcome = cycle(
                    state_dir=state_dir,
                    dispatch_job=supervisor.dispatch,
                    **cycle_kwargs,
                )
                cycles += 1
                last_state = getattr(outcome, "state", "")
                now = time.monotonic()
                if now >= next_source_check:
                    next_source_check = now + source_check_interval_seconds
                    if source_changed(baseline):
                        stop.set("source_changed")
                        break
                if stop_after_cycles is not None and cycles >= stop_after_cycles:
                    stop.set("cycle_cap")
                    break
                stop.wait(idle_tick_seconds)
            supervisor.drain(timeout=drain_timeout_seconds)
        finally:
            supervisor.pool.shutdown(wait=False)
        result = DaemonOutcome(
            stop.reason or "stopped",
            cycles=cycles,
            jobs_settled=supervisor.settled,
            last_state=last_state,
        )
    if result.reason == "source_changed":
        # Outside the lock: the replacement process takes it immediately.
        reload_exec(reload_argv)
    return result


__all__ = [
    "DRAIN_TIMEOUT_SECONDS",
    "IDLE_TICK_SECONDS",
    "SOURCE_CHECK_INTERVAL_SECONDS",
    "DaemonOutcome",
    "serve_forever",
]
