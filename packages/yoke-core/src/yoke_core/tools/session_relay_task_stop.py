"""Wait for an ended Windows relay task's process tree to exit.

Task Scheduler's End and the runner's kill-on-close job return before the
relay's launcher and workers exit, and Windows cannot delete a file a live
process holds open. Uninstall waits here, bounded, before it removes files.
"""

from __future__ import annotations

import os
from pathlib import Path
import time
from typing import Callable, Iterable

from yoke_contracts.designed_wait import announce_designed_wait
from yoke_contracts.platform_process import ProcessInfo, process_command_lines
from yoke_contracts.refusal_recovery import compose_refusal
from yoke_core.domain.relay_launchd_status import RelayInstallError

RELAY_STOP_WAIT_SECONDS = 30.0
RELAY_STOP_CODE = "uninstall_relay_not_stopped"
#: Task Scheduler's TASK_STATE_RUNNING.
TASK_RUNNING = "4"


def _not_stopped(what: str) -> RelayInstallError:
    return RelayInstallError(
        compose_refusal(
            f"{RELAY_STOP_CODE}: {what} still running after "
            f"{RELAY_STOP_WAIT_SECONDS:g}s",
            recovery="end it from Task Manager or `taskkill /PID <pid> /T /F`, then "
            "retry the uninstall; the relay's files, the machine home and the CLI "
            "were kept",
        ),
        code=RELAY_STOP_CODE,
    )


def _under(state_dir: Path) -> Callable[[ProcessInfo], bool]:
    roots = {os.path.normcase(str(path)) for path in (Path(state_dir), Path(state_dir).resolve())}

    def held(process: ProcessInfo) -> bool:
        for argument in process.cmdline:
            value = os.path.normcase(argument)
            if any(value == root or value.startswith(root + os.sep) for root in roots):
                return True
        return False

    return held


def relay_processes(state_dir: Path, processes: Iterable[ProcessInfo]) -> list[ProcessInfo]:
    """Processes other than this one whose command line names a path in *state_dir*."""
    held = _under(state_dir)
    return [process for process in processes if process.pid != os.getpid() and held(process)]


def wait_relay_task_stopped(
    *,
    state_dir: Path,
    task_state: Callable[[], str] | None,
    task_name: str,
    processes: Callable[[], list[ProcessInfo]] = process_command_lines,
) -> None:
    """Return once the task leaves Running and no process runs from *state_dir*.

    *task_state* is None when the task was not running or is already gone.
    Raises ``uninstall_relay_not_stopped`` naming the task or PIDs at the bound.
    """
    deadline = time.monotonic() + RELAY_STOP_WAIT_SECONDS
    announced = False

    def pause() -> None:
        nonlocal announced
        if not announced:
            announce_designed_wait(
                "relay processes to exit before removal",
                max_wait_seconds=RELAY_STOP_WAIT_SECONDS,
                cadence="every 250ms",
            )
            announced = True
        time.sleep(0.25)

    if task_state is not None:
        while task_state() == TASK_RUNNING:
            if time.monotonic() >= deadline:
                raise _not_stopped(f"scheduled task {task_name!r}")
            pause()
    while running := relay_processes(state_dir, processes()):
        if time.monotonic() >= deadline:
            pids = ", ".join(f"PID {process.pid}" for process in running)
            raise _not_stopped(f"relay process {pids} under {state_dir}")
        pause()


__all__ = [
    "RELAY_STOP_CODE",
    "RELAY_STOP_WAIT_SECONDS",
    "relay_processes",
    "wait_relay_task_stopped",
]
