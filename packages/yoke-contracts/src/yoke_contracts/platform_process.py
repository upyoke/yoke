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

import psutil


@dataclass(frozen=True)
class ProcessInfo:
    pid: int
    ppid: int
    cmdline: tuple[str, ...]
    start_time: float
    name: str
    rss_kb: int
    username: str


def _info(process: psutil.Process) -> ProcessInfo:
    with process.oneshot():
        if process.status() == psutil.STATUS_ZOMBIE:
            raise psutil.ZombieProcess(process.pid)
        argv = tuple(process.cmdline())
        return ProcessInfo(
            process.pid, process.ppid(), argv, process.create_time(),
            (Path(argv[0]).name if argv else process.name()),
            process.memory_info().rss // 1024, process.username(),
        )


def pid_alive(pid: int, start_time: float | None = None) -> bool:
    """Check liveness, optionally rejecting reuse of a recorded PID."""
    if pid <= 0:
        return False
    try:
        process = psutil.Process(pid)
        return (process.is_running() and process.status() != psutil.STATUS_ZOMBIE
                and (start_time is None or process.create_time() == float(start_time)))
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
                raise ValueError("invalid_process_identity: record positive PID and creation time")
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
                members.append((child.pid, child.create_time()))
            except psutil.NoSuchProcess:
                continue
        if not pid_alive(pid, start_time):
            return None
        return GroupHandle(pid, float(start_time), tuple(members))
    except psutil.Error as exc:
        raise OSError(f"process_capture_failed: PID {pid}; run as its owner and retry") from exc


def spawn_group(argv, **popen_kwargs) -> GroupHandle:
    """Spawn isolated work. Call stop_group to terminate it and its descendants."""
    if "preexec_fn" in popen_kwargs or "start_new_session" in popen_kwargs:
        raise ValueError("process_group_options_owned: remove preexec_fn/start_new_session")
    if os.name == "nt":
        from yoke_contracts.platform_process_windows import spawn
        return spawn(argv, popen_kwargs)
    process = subprocess.Popen(argv, start_new_session=True, **popen_kwargs)
    try:
        stamp = psutil.Process(process.pid).create_time()
    except psutil.NoSuchProcess:
        process.wait()
        raise OSError("process_spawn_exited: child exited before custody; inspect child output")
    return GroupHandle(process.pid, stamp, ((process.pid, stamp),), process,
                        _owns_session=True)


def stop_group(handle: GroupHandle, timeout: float) -> bool:
    """Return whether running members were found; terminate then kill after timeout.

    Identity uses exact creation time equality, never a PID-only or fuzzy match.
    Permission failures raise OSError; survivors raise TimeoutError with recovery.
    """
    if timeout < 0 or not math.isfinite(timeout):
        raise ValueError("invalid_stop_timeout: use a finite nonnegative timeout")
    processes = {}
    try:
        for pid, stamp in handle.members:
            if not pid_alive(pid, stamp):
                continue
            process = psutil.Process(pid)
            if process.create_time() != stamp:
                continue
            processes[pid] = process
            for child in process.children(recursive=True):
                processes[child.pid] = child
        # Only a live, verified leader authorizes signalling a POSIX group.
        if os.name != "nt" and handle._owns_session and pid_alive(handle.pid, handle.start_time):
            os.killpg(handle.pid, signal.SIGTERM)
        if os.name == "nt" and handle.process is not None and processes:
            try:
                handle.process.send_signal(signal.CTRL_BREAK_EVENT)
            except OSError:
                pass  # No attached console: the verified tree still stops below.
        for process in reversed(list(processes.values())):
            try:
                process.terminate()
            except psutil.NoSuchProcess:
                pass
        _, alive = psutil.wait_procs(list(processes.values()), timeout=timeout)
        if handle._job is not None:
            handle._job.terminate()
        for process in alive:
            try:
                process.kill()
            except psutil.NoSuchProcess:
                pass
        _, alive = psutil.wait_procs(alive, timeout=timeout)
        alive = [p for p in alive if pid_alive(p.pid, p.create_time())]
        if alive:
            raise TimeoutError(f"process_stop_timeout: PIDs {[p.pid for p in alive]}; close their owner and retry")
        if handle.process is not None:
            handle.process.wait(timeout=timeout)
        return bool(processes)
    except psutil.Error as exc:
        raise OSError(f"process_stop_failed: PID {handle.pid}; run as its owner and retry") from exc
    finally:
        if handle._job is not None:
            handle._job.close()
            handle._job = None


__all__ = ["ProcessInfo", "GroupHandle", "pid_alive", "process_command_lines",
           "ancestors", "handle_from_pid", "spawn_group", "stop_group"]
