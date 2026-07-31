"""Launch child processes in their own group and reap the whole tree.

``subprocess`` terminates only the process it started. A test runner
launched through a shell — ``sh -c 'pytest …'``, or pytest itself spawning
xdist workers — leaves grandchildren running when the parent is interrupted
or times out. Those survivors keep their PostgreSQL connections open, so the
databases they hold cannot be dropped and the next run blocks behind them.

Putting the child in a fresh process group makes the whole tree addressable:
one signal to the group reaches every descendant that has not itself started
a new session. Callers get two shapes:

- :func:`popen_in_process_group` + :func:`interruption_reaps_process_group`
  for streaming callers that read the child's output as it runs.
- :func:`run_in_process_group` for call-and-collect callers that want
  ``subprocess.run`` semantics with a timeout that actually reaps.

A process group cannot be signalled on platforms without ``killpg``; there
the helpers degrade to signalling the direct child, which is exactly the
behavior callers had before.
"""

from __future__ import annotations

import contextlib
import os
import signal
import subprocess
import threading
from typing import Iterator, Sequence

#: Seconds a terminated group is given to exit before it is killed outright.
DEFAULT_GRACE_SECONDS = 5.0

_GROUP_SIGNALS_SUPPORTED = hasattr(os, "killpg") and hasattr(os, "getpgid")


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
    """Start *argv* as the leader of a new process group.

    ``start_new_session`` also detaches the child from the terminal's
    foreground group, so an interactive Ctrl-C reaches this process alone.
    That is deliberate: the parent decides when the tree dies, and it always
    reaps the group rather than leaving orphans behind.
    """
    kwargs.setdefault("start_new_session", True)
    return subprocess.Popen(argv, **kwargs)


def _group_id(proc: subprocess.Popen) -> int | None:
    """Return the child's process-group id, or None when it cannot be used."""
    if not _GROUP_SIGNALS_SUPPORTED:
        return None
    try:
        pgid = os.getpgid(proc.pid)
    except (ProcessLookupError, PermissionError, OSError):
        return None
    # Signalling our own group would take down this process and its siblings.
    # That only happens when the child was started without a new session, in
    # which case the direct-child fallback is the correct, narrower action.
    if pgid == os.getpgid(0):
        return None
    return pgid


def _descendant_pids(root_pid: int) -> list[int]:
    """Return every live descendant of *root_pid*, deepest last.

    Signalling a process group does not reach a descendant that started its own
    session — and nesting is normal here, because a runner launched under one
    supervisor puts its own child in a fresh session so that IT can reap
    precisely. Walking parent links reaches those grandchildren regardless of
    which session they moved to.
    """
    try:
        listing = subprocess.run(
            ["ps", "-eo", "pid=,ppid="],
            capture_output=True,
            text=True,
            timeout=10,
        ).stdout
    except (OSError, subprocess.SubprocessError):
        return []

    children: dict[int, list[int]] = {}
    for line in listing.splitlines():
        parts = line.split()
        if len(parts) != 2:
            continue
        try:
            pid, ppid = int(parts[0]), int(parts[1])
        except ValueError:
            continue
        children.setdefault(ppid, []).append(pid)

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


def _signal_tree(proc: subprocess.Popen, pgid: int | None, signal_number: int) -> None:
    # Collect descendants BEFORE signalling: once the direct child dies its
    # children are reparented away and the parent links that identify them are
    # gone, which is exactly how an orphaned test runner survives its reaper.
    descendants = _descendant_pids(proc.pid)
    try:
        if pgid is not None:
            os.killpg(pgid, signal_number)
        else:
            proc.send_signal(signal_number)
    except (ProcessLookupError, PermissionError, OSError):
        pass  # Already gone, or no longer ours to signal.
    for pid in descendants:
        try:
            os.kill(pid, signal_number)
        except (ProcessLookupError, PermissionError, OSError):
            pass


def terminate_process_group(
    proc: subprocess.Popen, *, grace_seconds: float = DEFAULT_GRACE_SECONDS
) -> None:
    """Terminate *proc*'s whole group, then reap it.

    Sends ``SIGTERM`` so a test runner can still tear its own fixtures down,
    then ``SIGKILL`` to whatever ignored it. Returns once the direct child has
    been waited on, so the caller never leaves a zombie.
    """
    if proc.poll() is not None:
        with contextlib.suppress(Exception):
            proc.wait(timeout=grace_seconds)
        return

    pgid = _group_id(proc)
    _signal_tree(proc, pgid, signal.SIGTERM)
    try:
        proc.wait(timeout=grace_seconds)
        return
    except subprocess.TimeoutExpired:
        pass

    _signal_tree(proc, pgid, signal.SIGKILL)
    with contextlib.suppress(subprocess.TimeoutExpired):
        proc.wait(timeout=grace_seconds)


@contextlib.contextmanager
def interruption_reaps_process_group(
    proc: subprocess.Popen, *, grace_seconds: float = DEFAULT_GRACE_SECONDS
) -> Iterator[None]:
    """Reap *proc*'s group when the guarded block is interrupted.

    Covers all three ways a long watcher actually dies: an exception in the
    reading loop, a Ctrl-C, and the ``SIGTERM`` a harness sends when it gives
    up on a run. ``SIGKILL`` cannot be handled by anyone, which is why the
    orphan sweep remains the backstop rather than the primary mechanism.

    Handlers are installed only on the main thread, since that is the only
    thread :mod:`signal` permits them on; elsewhere the exception path still
    reaps.
    """
    handled = (signal.SIGINT, signal.SIGTERM)
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


def run_in_process_group(
    argv: str | Sequence[str],
    *,
    timeout: float | None = None,
    capture_output: bool = False,
    grace_seconds: float = DEFAULT_GRACE_SECONDS,
    **kwargs,
) -> subprocess.CompletedProcess:
    """Run *argv* to completion, reaping the whole group on timeout.

    Mirrors :func:`subprocess.run`, including the
    :class:`subprocess.TimeoutExpired` it raises, but kills every descendant
    instead of only the direct child — the difference between a timed-out run
    that releases its databases and one that wedges the cluster.
    """
    if capture_output:
        kwargs.setdefault("stdout", subprocess.PIPE)
        kwargs.setdefault("stderr", subprocess.PIPE)

    proc = popen_in_process_group(argv, **kwargs)
    try:
        stdout, stderr = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        terminate_process_group(proc, grace_seconds=grace_seconds)
        stdout, stderr = proc.communicate()
        raise subprocess.TimeoutExpired(
            argv, timeout, output=stdout, stderr=stderr
        )
    except BaseException:
        terminate_process_group(proc, grace_seconds=grace_seconds)
        raise
    return subprocess.CompletedProcess(argv, proc.returncode, stdout, stderr)


__all__ = [
    "DEFAULT_GRACE_SECONDS",
    "ProcessGroupInterrupted",
    "interruption_reaps_process_group",
    "popen_in_process_group",
    "run_in_process_group",
    "terminate_process_group",
]
