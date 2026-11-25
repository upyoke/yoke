"""One release-pinned relay process per machine: poll, supervise, repin.

A relay that is respawned on a timer pays a fresh interpreter for every
poll and, worse, hands each job a lifetime no longer than the spawn that
leased it — a launch or wake whose process outlives its poll cycle dies
with it and settles as a lost lease. This module keeps one process alive
instead:

* the run lock is taken once, for the daemon's whole life, so a second
  relay on the machine cannot interleave between cycles of the first;
* machine-local maintenance runs before every poll, so custody cleanup also
  reaches natives created after daemon startup;
* leased jobs settle on a supervised worker pool whose lifetime is the
  job's, so the poll loop is never blocked behind one and a job finishes
  even though several cycles roll past it;
* because the loop is never blocked, its own claim keeps the machine's
  ``session_relays`` row and surface inventory continuously published —
  the state gap that appears while a long job holds a one-shot process;
* termination interrupts main-thread IO and bounds settlement below the loaded
  service manager's stop deadline; release repinning retains its own window.
  Durable leases, native custody and pending reports survive interrupted jobs.

Failure bursts log immediately, periodically, and on recovery; a failed poll
backs off exponentially. A credential rejected for good stops the daemon with
exit 0, which the service manager does not restart.

A new served build installs on a background thread beside the running
release while the loop keeps polling. After draining, the daemon restarts on
the new pin. A failed install leaves the prior process working and is not
retried for the same build (see ``session_relay_release_pin``).
For a local universe, a changed installed release drains the daemon and exits
so the service supervisor reruns the stable CLI launcher.
"""

from __future__ import annotations

from dataclasses import dataclass
import logging
from pathlib import Path
import random
import sys
import time
from typing import Callable, Sequence

from yoke_contracts.session_control.relay_health import RELAY_NEWER_THAN_SERVER
from yoke_cli.transport import control_plane_payload
from yoke_harness.session_relay import (
    CREDENTIAL_REJECTED,
    ServeOnceOutcome,
    run_serve_cycle,
)
from yoke_harness.session_relay_failure_log import FailureReporter
from yoke_harness.session_relay_supervision import RelayStopRequested, Supervisor
from yoke_harness.session_relay_poll_health import (
    connection_recovery,
    record_poll_failure,
    reset_poll_outcome,
)
from yoke_harness.session_relay_schedule import (
    record_next_poll,
    relay_run_lock,
    relay_state_dir,
)
from yoke_harness.session_relay_process_restart import exec_relay_release
from yoke_harness.session_relay_release_pin import PinServedRelease, ReleasePinner
from yoke_harness.session_relay_stop_deadline import read_stop_settlement_seconds
from yoke_harness.session_relay_stop_request import (
    StopRequest,
    install_signal_handlers,
    restore_signal_handlers,
)


# How long the loop waits between cadence checks. The server owns the poll
# cadence; this only bounds how fast the daemon notices a stop request.
IDLE_TICK_SECONDS = 0.5

# Longest wait for in-flight jobs once the daemon has stopped starting new
# work. A native launch that has not settled by then is already supervised
# by its own attempt record, so waiting past this only delays the restart.
DRAIN_TIMEOUT_SECONDS = 120

# Doubles per consecutive failed poll, jittered so machines do not retry in step.
POLL_BACKOFF_INITIAL_SECONDS = 5
POLL_BACKOFF_MAX_SECONDS = 300

_LOGGER = logging.getLogger(__name__)


def poll_backoff_seconds(consecutive_failures: int) -> int:
    exponent = min(max(consecutive_failures, 1) - 1, 16)
    ceiling = min(POLL_BACKOFF_MAX_SECONDS, POLL_BACKOFF_INITIAL_SECONDS << exponent)
    return random.randint(max(1, ceiling // 2), ceiling)


def _observed_server_build() -> control_plane_payload.ObservedServerBuild:
    """Build carried by the latest response in this poll's handshake."""
    return control_plane_payload.current_server_build()


@dataclass
class DaemonOutcome:
    """Why the daemon returned, and what it settled on the way out."""

    reason: str
    cycles: int = 0
    jobs_settled: int = 0
    last_state: str = ""


def serve_forever(
    *,
    state_dir: Path | None = None,
    cycle: Callable[..., ServeOnceOutcome] = run_serve_cycle,
    cycle_maintenance: Callable[[], None] | None = None,
    stop_after_cycles: int | None = None,
    idle_tick_seconds: float = IDLE_TICK_SECONDS,
    drain_timeout_seconds: float = DRAIN_TIMEOUT_SECONDS,
    max_job_workers: int = 4,
    reload_check: Callable[[], bool] | None = None,
    reload_argv: Sequence[str] | None = None,
    reload_exec: Callable[..., None] = exec_relay_release,
    pinned_release: str = "",
    pin_served_release: PinServedRelease | None = None,
    served_build_observer: Callable[
        [], control_plane_payload.ObservedServerBuild
    ] = _observed_server_build,
    install_signals: bool = True,
    **cycle_kwargs: object,
) -> DaemonOutcome:
    """Serve until a signal, a release restart, or a direct cap.

    ``stop_after_cycles`` bounds the loop for callers that drive it
    directly; the installed service leaves it unset and runs until the
    machine stops it.
    """
    stop = StopRequest()
    stop_settlement_seconds = read_stop_settlement_seconds()
    prior_handlers = install_signal_handlers(stop) if install_signals else {}
    try:
        return _serve_under_lock(
            stop,
            state_dir=state_dir,
            cycle=cycle,
            cycle_maintenance=cycle_maintenance,
            stop_after_cycles=stop_after_cycles,
            idle_tick_seconds=idle_tick_seconds,
            drain_timeout_seconds=drain_timeout_seconds,
            stop_settlement_seconds=stop_settlement_seconds,
            max_job_workers=max_job_workers,
            reload_check=reload_check,
            reload_argv=reload_argv,
            reload_exec=reload_exec,
            pinned_release=pinned_release,
            pin_served_release=pin_served_release,
            served_build_observer=served_build_observer,
            **cycle_kwargs,
        )
    finally:
        restore_signal_handlers(prior_handlers)


def _serve_under_lock(
    stop: StopRequest,
    *,
    state_dir: Path | None,
    cycle: Callable[..., ServeOnceOutcome],
    cycle_maintenance: Callable[[], None] | None,
    stop_after_cycles: int | None,
    idle_tick_seconds: float,
    drain_timeout_seconds: float,
    stop_settlement_seconds: float,
    max_job_workers: int,
    reload_check: Callable[[], bool] | None,
    reload_argv: Sequence[str] | None,
    reload_exec: Callable[..., None],
    pinned_release: str,
    pin_served_release: PinServedRelease | None,
    served_build_observer: Callable[[], control_plane_payload.ObservedServerBuild],
    **cycle_kwargs: object,
) -> DaemonOutcome:
    """Hold the machine's relay lock for as long as this daemon serves."""
    resolved = state_dir if state_dir is not None else relay_state_dir()
    with relay_run_lock(resolved) as acquired:
        if not acquired:
            return DaemonOutcome("locked")
        failures = FailureReporter(state_dir=resolved)
        reset_poll_outcome(resolved)
        supervisor = Supervisor(max_job_workers, failures, stop)
        pinner = (
            ReleasePinner(
                pin_served_release,
                pinned_release=pinned_release,
                state_dir=resolved,
                failures=failures,
            )
            if pin_served_release is not None
            else None
        )
        cycles = 0
        failed_polls = 0
        last_state = ""
        replacement: Path | None = None
        try:
            while not stop.is_set():
                if reload_check is not None and reload_check():
                    stop.set("installed_release_changed")
                    print(
                        "relay reloading: installed release changed (installed_release_changed)",
                        file=sys.stderr,
                        flush=True,
                    )
                    break
                observation_before = served_build_observer() if pinner else None
                try:
                    if cycle_maintenance is not None:
                        cycle_maintenance()
                    outcome = cycle(
                        state_dir=resolved,
                        dispatch_job=supervisor.dispatch,
                        **cycle_kwargs,
                    )
                except Exception as exc:  # noqa: BLE001 — keep the relay standing
                    failures.failed("poll", f"{type(exc).__name__}: {exc}")
                    last_state = "poll_failed"
                else:
                    last_state = str(getattr(outcome, "state", ""))
                    if last_state == CREDENTIAL_REJECTED:
                        code = str(getattr(outcome, "error_code", None) or last_state)
                        record_poll_failure(resolved, error_code=code)
                        _LOGGER.error(
                            "relay stopped: credential rejected (%s); "
                            "class=relay_failure outcome=stopped recovery=%s",
                            code,
                            connection_recovery(code),
                        )
                        stop.set(CREDENTIAL_REJECTED)
                        break
                    if last_state in {"claim_failed", RELAY_NEWER_THAN_SERVER}:
                        code = getattr(outcome, "error_code", None) or last_state
                        failures.failed(
                            "poll",
                            getattr(outcome, "error_detail", None) or code,
                            persist_code=code,
                        )
                    elif last_state == "report_failed":
                        failures.failed(
                            "report",
                            getattr(outcome, "error_code", None) or last_state,
                        )
                    elif last_state != "backoff":
                        failures.recovered("poll")
                        if last_state == "reported":
                            failures.recovered("report")
                cycles += 1
                if last_state in {"claim_failed", "poll_failed"}:
                    failed_polls += 1
                    record_next_poll(
                        poll_backoff_seconds(failed_polls),
                        resolved,
                        started_at=time.time(),
                    )
                elif last_state != "backoff":
                    failed_polls = 0
                if pinner is not None and observation_before is not None:
                    # Only a fresh handshake proves what the server serves now.
                    observed = served_build_observer()
                    if observed.observation > observation_before.observation:
                        pinner.offer(observed.name)
                    replacement = pinner.settle()
                    if replacement is not None:
                        stop.set("served_build_changed")
                        break
                if stop_after_cycles is not None and cycles >= stop_after_cycles:
                    stop.set("cycle_cap")
                    break
                if idle_tick_seconds > 0:
                    time.sleep(idle_tick_seconds)
            supervisor.drain(timeout=drain_timeout_seconds)
        except RelayStopRequested:
            if pinner is not None:
                pinner.cancel(0)
            supervisor.pool.shutdown(wait=False, cancel_futures=False)
            remaining = stop.requested_at + stop_settlement_seconds - time.monotonic()
            supervisor.drain(timeout=remaining)
        finally:
            if pinner is not None:
                pinner.cancel(stop.requested_at + stop_settlement_seconds - time.monotonic())
            supervisor.pool.shutdown(wait=False, cancel_futures=False)
        result = DaemonOutcome(
            stop.reason or "stopped",
            cycles=cycles,
            jobs_settled=supervisor.settled,
            last_state=last_state,
        )
    # Restart outside the lock so the replacement can acquire it.
    if result.reason in {"installed_release_changed", "served_build_changed"}:
        reload_exec(reload_argv, executable=str(replacement) if replacement else None)
    return result


__all__ = [
    "DRAIN_TIMEOUT_SECONDS",
    "IDLE_TICK_SECONDS",
    "DaemonOutcome",
    "poll_backoff_seconds",
    "serve_forever",
]
