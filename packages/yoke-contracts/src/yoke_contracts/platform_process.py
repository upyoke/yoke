"""Portable process observation and identity-checked process-tree custody.

Snapshots are lists of ProcessInfo, not mappings. Spawned work survives creator
exit (no kill-on-job-close); stop_group explicitly ends its custody. Persist GroupHandle.to_record()
for custody across restarts, then restore with GroupHandle.from_record(). A newly
spawned handle exposes its Popen as .process; a restored one has process=None.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import math
import os
from pathlib import Path
import signal
import subprocess
import time

import psutil


@dataclass(frozen=True)
class ProcessInfo:
    """One observed process. ``start_time`` is its start_identity, not a clock
    reading; ``created_at`` is the wall-clock creation epoch, for time reads."""

    pid: int
    ppid: int
    cmdline: tuple[str, ...]
    start_time: float
    name: str
    rss_kb: int
    username: str
    created_at: float


# psutil's own reuse check reads these platforms' kernel start unadjusted.
_MONOTONIC_START = psutil.LINUX or psutil.OSX or psutil.BSD


def start_identity(process: psutil.Process) -> float:
    """Return the clock-stable start token that identifies this process.

    psutil's create_time() shifts with the wall clock on Linux and macOS (by
    the boot-time delta each importer sees), so two readers either side of a
    clock step disagree. Record and compare only this value, by exact
    equality: the raw kernel start on Linux/macOS/BSD, the never-adjusted
    FILETIME creation on Windows.
    """
    if _MONOTONIC_START:
        return process._proc.create_time(monotonic=True)
    return process.create_time()


def _info(process: psutil.Process) -> ProcessInfo:
    with process.oneshot():
        if process.status() == psutil.STATUS_ZOMBIE:
            raise psutil.ZombieProcess(process.pid)
        argv = tuple(process.cmdline())
        return ProcessInfo(
            process.pid, process.ppid(), argv, start_identity(process),
            (Path(argv[0]).name if argv else process.name()),
            process.memory_info().rss // 1024, process.username(),
            process.create_time(),
        )


def pid_alive(pid: int, start_time: float | None = None) -> bool:
    """Check liveness, optionally rejecting reuse of a recorded start_identity."""
    if pid <= 0:
        return False
    try:
        process = psutil.Process(pid)
        return (process.is_running() and process.status() != psutil.STATUS_ZOMBIE
                and (start_time is None or start_identity(process) == float(start_time)))
    except psutil.NoSuchProcess:
        return False
    except psutil.AccessDenied as exc:
        raise OSError(f"process_access_denied: PID {pid}; run as its owner") from exc


def process_command_lines() -> list[ProcessInfo]:
    """Snapshot visible processes; inaccessible/exited processes are omitted."""
    result = []
    for process in psutil.process_iter():
        try:
            result.append(_info(process))
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    return result


def ancestors(pid: int) -> list[ProcessInfo]:
    """Return the visible parent prefix, nearest first, stopping at denied/exited parents."""
    result = []
    try:
        for parent in psutil.Process(pid).parents():
            try:
                result.append(_info(parent))
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                break
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        pass
    return result


def process_info(pid: int) -> ProcessInfo | None:
    """Read one process without snapshotting the table; None when exited or denied."""
    if pid <= 0:
        return None
    try:
        return _info(psutil.Process(pid))
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        return None


@dataclass
class GroupHandle:
    pid: int
    start_time: float
    members: tuple[tuple[int, float], ...]
    process: subprocess.Popen | None = field(default=None, repr=False)
    _job: object | None = field(default=None, repr=False)
    _owns_session: bool = False

    def to_record(self) -> dict:
        """JSON-safe identity records; kernel handles never cross restarts."""
        captured = dict(self.members)
        for pid, stamp in self.members:
            group = handle_from_pid(pid, stamp)
            if group is not None:
                captured.update(group.members)
        self.members = tuple(captured.items())
        return {"pid": self.pid, "start_time": self.start_time,
                "members": [[pid, stamp] for pid, stamp in self.members]}

    @classmethod
    def from_record(cls, record: dict) -> GroupHandle:
        """Restore captured identities, including members whose leader exited."""
        def identity(pid, stamp):
            pid, stamp = int(pid), float(stamp)
            if pid <= 0 or not math.isfinite(stamp) or stamp <= 0:
                raise ValueError("invalid_process_identity: record positive PID and start identity")
            return pid, stamp
        pid, stamp = identity(record["pid"], record["start_time"])
        members = tuple(identity(*pair) for pair in record["members"])
        return cls(pid, stamp, members)


def handle_from_pid(pid: int, start_time: float) -> GroupHandle | None:
    """Capture a verified existing process and its descendants for later stop."""
    if not pid_alive(pid, start_time):
        return None
    try:
        root = psutil.Process(pid)
        members = [(pid, float(start_time))]
        for child in root.children(recursive=True):
            try:
                members.append((child.pid, start_identity(child)))
            except psutil.NoSuchProcess:
                continue
        if not pid_alive(pid, start_time):
            return None
        return GroupHandle(pid, float(start_time), tuple(members))
    except psutil.NoSuchProcess:
        return None
    except psutil.Error as exc:
        raise OSError(f"process_capture_failed: PID {pid}; run as its owner and retry") from exc


def detach_current_process() -> None:
    """Detach the forked POSIX supervisor from its SSH terminal."""
    if os.name == "nt":
        raise OSError("platform_unsupported: POSIX supervisor unavailable; use native process custody")
    os.setsid()


def spawn_group_process(argv, **popen_kwargs) -> subprocess.Popen:
    """Spawn the POSIX stdlib boundary, also embedded in pre-install SSH payloads.

    Installed callers use spawn_group to retain identity-checked custody. The
    standalone Linux subreaper owns identities through its /proc receipt instead.
    """
    if os.name == "nt":
        raise OSError("platform_unsupported: POSIX spawn boundary unavailable; use spawn_group")
    if "preexec_fn" in popen_kwargs or "start_new_session" in popen_kwargs:
        raise ValueError("process_group_options_owned: remove preexec_fn/start_new_session")
    return subprocess.Popen(argv, start_new_session=True, **popen_kwargs)


def spawn_group(argv, **popen_kwargs) -> GroupHandle:
    """Spawn isolated work. Call stop_group to terminate it and its descendants."""
    if "preexec_fn" in popen_kwargs or "start_new_session" in popen_kwargs:
        raise ValueError("process_group_options_owned: remove preexec_fn/start_new_session")
    if os.name == "nt":
        from yoke_contracts.platform_process_windows import spawn
        return spawn(argv, popen_kwargs)
    process = spawn_group_process(argv, **popen_kwargs)
    try:
        stamp = start_identity(psutil.Process(process.pid))
    except psutil.NoSuchProcess:
        process.wait()
        raise OSError("process_spawn_exited: child exited before custody; inspect child output")
    return GroupHandle(process.pid, stamp, ((process.pid, stamp),), process,
                        _owns_session=True)


def _signal(process: psutil.Process, kill: bool, denied: set[int]) -> None:
    """Signal one verified process; an exit already under way is not a failure.

    Windows refuses OpenProcess/TerminateProcess with access denied while a
    process is exiting, so a denial only counts if the process outlives the wait.
    """
    try:
        process.kill() if kill else process.terminate()
    except psutil.NoSuchProcess:
        pass
    except psutil.AccessDenied:
        denied.add(process.pid)


def _survivors(processes, timeout: float) -> list[tuple[psutil.Process, float]]:
    """Poll (process, start_identity) pairs until all exit or the timeout passes.

    Identities are captured while each process is verified live: an exited
    process has no start to read back.
    """
    deadline = time.monotonic() + timeout
    while True:
        alive = [(p, stamp) for p, stamp in processes if pid_alive(p.pid, stamp)]
        if not alive or time.monotonic() >= deadline:
            return alive
        time.sleep(0.02)


def stop_group(handle: GroupHandle, timeout: float) -> bool:
    """Return whether running members were found; terminate then kill after timeout.

    Identity uses exact start_identity equality, never a PID-only or fuzzy match.
    A member that exits while the stop runs counts as stopped, including one
    whose exit made Windows deny a signal or Darwin deny killpg with EPERM. A
    survivor of a refused signal raises PermissionError; other survivors raise
    TimeoutError.
    """
    if timeout < 0 or not math.isfinite(timeout):
        raise ValueError("invalid_stop_timeout: use a finite nonnegative timeout")
    processes = {}
    try:
        job_running = handle._job is not None and handle._job.has_active_processes()
        for pid, stamp in handle.members:
            if not pid_alive(pid, stamp):
                continue
            try:
                process = psutil.Process(pid)
                if start_identity(process) != stamp:
                    continue
                descendants = process.children(recursive=True)
            except psutil.NoSuchProcess:
                continue  # Exited after the liveness check: nothing left to stop.
            processes[pid] = (process, stamp)
            for child in descendants:
                try:
                    processes[child.pid] = (child, start_identity(child))
                except psutil.NoSuchProcess:
                    continue
        denied: set[int] = set()
        group_refused = False
        # Only a live, verified leader authorizes signalling a POSIX group.
        if os.name != "nt" and handle._owns_session and pid_alive(handle.pid, handle.start_time):
            try:
                os.killpg(handle.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            except PermissionError:
                # Darwin refuses killpg with EPERM once the group holds only a
                # zombie; the verified members below decide whether it stopped.
                group_refused = True
        console_stop = False
        # Only spawn_group owns a known CREATE_NEW_PROCESS_GROUP console group.
        # Restored/adopted PIDs can share our console and must never get a break.
        if os.name == "nt" and handle._job is not None and handle.pid in processes:
            try:
                processes[handle.pid][0].send_signal(signal.CTRL_BREAK_EVENT)
                console_stop = True
            except (OSError, psutil.Error):
                pass  # No attached console: the verified tree still stops below.
        if not console_stop:
            for process, _ in reversed(list(processes.values())):
                _signal(process, False, denied)
        alive = _survivors(processes.values(), timeout)
        if handle._job is not None:
            handle._job.terminate()
        for process, _ in alive:
            _signal(process, True, denied)
        alive = [p.pid for p, _ in _survivors(alive, timeout)]
        refused = [pid for pid in alive if group_refused or pid in denied]
        if refused:
            raise PermissionError(f"process_access_denied: PIDs {refused} refused stop; run as their owner and retry")
        if alive:
            raise TimeoutError(f"process_stop_timeout: PIDs {alive}; close their owner and retry")
        if handle.process is not None:
            handle.process.wait(timeout=timeout)
        return bool(processes) or job_running
    except psutil.Error as exc:
        raise OSError(f"process_stop_failed: PID {handle.pid}: {exc}; run as its owner and retry") from exc
    finally:
        if handle._job is not None:
            handle._job.close()
            handle._job = None


__all__ = ["ProcessInfo", "GroupHandle", "start_identity", "pid_alive", "process_command_lines", "process_info",
           "ancestors", "handle_from_pid", "spawn_group", "stop_group", "spawn_group_process", "detach_current_process"]
