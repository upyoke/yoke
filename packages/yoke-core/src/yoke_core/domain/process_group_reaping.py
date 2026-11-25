"""Launch child processes in their own group and reap the whole tree.

``subprocess`` terminates only the process it started. A test runner
launched through a shell — ``sh -c 'pytest …'``, or pytest itself spawning
xdist workers — leaves grandchildren running when the parent is interrupted
or times out. Those survivors keep their PostgreSQL connections open, so the
databases they hold cannot be dropped and the next run blocks behind them.

Putting the child in a fresh process group makes the whole tree addressable:
one signal to the group reaches every descendant that has not itself started
a new session. Streaming callers use :func:`popen_in_process_group` with
:func:`interruption_reaps_process_group` to read output as the child runs.

Process custody uses the shared platform owner on POSIX and Windows.
"""

from __future__ import annotations

from yoke_contracts.platform_process import process_command_lines, spawn_group, stop_group

import contextlib
import signal
import subprocess
import threading
from typing import Iterator

#: Seconds a terminated group is given to exit before it is killed outright.
DEFAULT_GRACE_SECONDS = 5.0


class ProcessGroupInterrupted(BaseException):
    """Raised when a signal interrupts a guarded process group.

    Derives from :class:`BaseException` rather than :class:`Exception` for the
    same reason :class:`KeyboardInterrupt` does: an interruption must not be
    swallowed by a broad ``except Exception`` somewhere up the stack.
    """

    def __init__(self, signal_number: int) -> None:
        super().__init__(f"interrupted by signal {signal_number}")
        self.signal_number = signal_number


def popen_in_process_group(argv, **kwargs) -> subprocess.Popen:
    """Spawn isolated work and retain its portable custody handle."""
    group = spawn_group(argv, **kwargs)
    proc = group.process
    proc._yoke_process_group = group
    return proc


def descendant_pids(root_pid: int) -> list[int]:
    """Return every live descendant of *root_pid*, deepest last.

    Signalling a process group does not reach a descendant that started its own
    session — and nesting is normal here, because a runner launched under one
    supervisor puts its own child in a fresh session so that IT can reap
    precisely. Walking parent links reaches those grandchildren regardless of
    which session they moved to.
    """
    children: dict[int, list[int]] = {}
    for process in process_command_lines():
        children.setdefault(process.ppid, []).append(process.pid)

    found: list[int] = []
    frontier = [root_pid]
    while frontier:
        current = frontier.pop()
        for child in children.get(current, ()):
            if child in found or child == root_pid:
                continue
            found.append(child)
            frontier.append(child)
    return found


def terminate_process_group(
    proc: subprocess.Popen, *, grace_seconds: float = DEFAULT_GRACE_SECONDS
) -> None:
    """Terminate and reap every identity held by this spawned process group."""
    stop_group(proc._yoke_process_group, timeout=grace_seconds)


@contextlib.contextmanager
def interruption_reaps_process_group(
    proc: subprocess.Popen, *, grace_seconds: float = DEFAULT_GRACE_SECONDS
) -> Iterator[None]:
    """Reap *proc*'s group when the guarded block is interrupted.

    Covers exceptions, Ctrl-C, harness ``SIGTERM``, and terminal-close
    ``SIGHUP``. ``SIGKILL`` cannot be handled by anyone, which is why the
    orphan sweep remains the backstop rather than the primary mechanism.

    Handlers are installed only on the main thread, since that is the only
    thread :mod:`signal` permits them on; elsewhere the exception path still
    reaps.
    """
    handled = (signal.SIGINT, signal.SIGTERM)
    if hasattr(signal, "SIGHUP"):
        handled += (signal.SIGHUP,)
    installable = threading.current_thread() is threading.main_thread()
    previous: dict[int, object] = {}

    def handle(signal_number: int, _frame) -> None:
        raise ProcessGroupInterrupted(signal_number)

    if installable:
        for signal_number in handled:
            with contextlib.suppress(ValueError, OSError):
                previous[signal_number] = signal.signal(signal_number, handle)
    try:
        yield
    except BaseException:
        terminate_process_group(proc, grace_seconds=grace_seconds)
        raise
    finally:
        for signal_number, handler in previous.items():
            with contextlib.suppress(ValueError, OSError):
                signal.signal(signal_number, handler)  # type: ignore[arg-type]

__all__ = [
    "DEFAULT_GRACE_SECONDS",
    "ProcessGroupInterrupted",
    "descendant_pids",
    "interruption_reaps_process_group",
    "popen_in_process_group",
    "terminate_process_group",
]
