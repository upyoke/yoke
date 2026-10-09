"""Identity-bound group observation and bounded physical termination.

Group ids alone can be reused. A surviving recorded member proves ownership;
without one, a populated group stays unresolved and is never signalled.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time
from typing import Any, Callable, Mapping

from yoke_contracts.process_ancestry import process_start_time

MAX_RECORD_BYTES = 4096
TERMINATE_WAIT_SECONDS = 2.0
SUCCESS_RESULTS = frozenset({"terminated", "killed", "already_exited"})


def group_members(group: int) -> dict[str, str]:
    """Read live members; observation failures raise instead of proving exit."""
    members = {}
    if sys.platform == "linux":
        for entry in Path("/proc").iterdir():
            if not entry.name.isdecimal():
                continue
            try:
                fields = (entry / "stat").read_text().rsplit(")", 1)[1].split()
            except (FileNotFoundError, ProcessLookupError):
                # A task may exit between enumeration and reading its stat.
                continue
            if int(fields[2]) == group and fields[0] != "Z":
                members[entry.name] = "linux:" + fields[19]
    else:
        result = subprocess.run(
            ["ps", "-axo", "pid=,pgid=,stat=,lstart="],
            capture_output=True,
            text=True,
            timeout=TERMINATE_WAIT_SECONDS,
            check=True,
        )
        for line in result.stdout.splitlines():
            pid, pgid, state, started = line.split(None, 3)
            if int(pgid) == group and not state.startswith("Z"):
                members[pid] = started.strip()
    return members


def capture_group(pid: int, started: str) -> dict[str, Any]:
    group = os.getpgid(pid)
    members = group_members(group)
    if (
        process_start_time(pid) != started
        or str(pid) not in members
        or os.getpgid(pid) != group
    ):
        raise OSError("process_identity_changed")
    return {"process_group_id": group, "group_members": members}


def custody_state(record: Mapping[str, Any]) -> str:
    """Return live, gone, or unresolved without signalling anything."""
    group = record.get("process_group_id")
    pid = record.get("pid") or record.get("anchor_pid")
    started = record.get("process_start_time") or record.get("anchor_start_time")
    try:
        if not isinstance(group, int):
            if process_start_time(pid) == started:
                return "live"
            # A reused pid must never be signalled. A missing identity probe
            # alone does not prove exit when the numeric pid still exists.
            try:
                os.kill(pid, 0)
            except ProcessLookupError:
                return "gone"
            return "gone" if process_start_time(pid) is not None else "unresolved"
        members = group_members(group)
        if not members:
            return "gone"
        recorded = dict(record.get("group_members") or {})
        recorded.setdefault(str(pid), started)
        return (
            "live"
            if any(members.get(p) == s for p, s in recorded.items())
            else "unresolved"
        )
    except (OSError, ValueError, TypeError, subprocess.SubprocessError):
        return "unresolved"


def write_record(path: Path, record: Mapping[str, Any]) -> bool:
    temporary = path.with_suffix(f".{os.getpid()}.tmp")
    try:
        body = json.dumps(dict(record), sort_keys=True)
        if len(body.encode()) > MAX_RECORD_BYTES:
            return False
        with temporary.open("w", encoding="utf-8") as handle:
            handle.write(body)
            handle.flush()
            os.fsync(handle.fileno())
        temporary.chmod(0o600)
        os.replace(temporary, path)
    except OSError:
        return False
    return True


def _wait_gone(record: Mapping[str, Any], wait_seconds: float) -> bool:
    deadline = time.monotonic() + wait_seconds
    while True:
        if custody_state(record) == "gone":
            return True
        if time.monotonic() >= deadline:
            return False
        time.sleep(min(0.1, max(0, deadline - time.monotonic())))


def terminate_record(
    record: dict[str, Any],
    *,
    wait_seconds: float = TERMINATE_WAIT_SECONDS,
    persist: Callable[[Mapping[str, Any]], bool] | None = None,
) -> str:
    """One TERM/KILL attempt, with identity and exit checked at each boundary."""
    state = custody_state(record)
    if state == "gone":
        return "already_exited"
    if state != "live":
        return "outcome_unknown"
    pid = record.get("pid") or record.get("anchor_pid")
    started = record.get("process_start_time") or record.get("anchor_start_time")
    try:
        if not isinstance(record.get("process_group_id"), int):
            record.update(capture_group(pid, started))
        group = record["process_group_id"]
        if group == os.getpgrp():
            return "shared_process_group"
        # Retain survivors before TERM can kill their supervisor. A retry can
        # then recognize the same group even after its leader has gone.
        record["group_members"] = group_members(group)
        if custody_state(record) != "live" or (
            persist is not None and not persist(record)
        ):
            return "outcome_unknown"
        for sig, success in (
            (signal.SIGTERM, "terminated"),
            (signal.SIGKILL, "killed"),
        ):
            state = custody_state(record)
            if state == "gone":
                return "terminated"
            if state != "live":
                return "outcome_unknown"
            try:
                os.killpg(group, sig)
            except ProcessLookupError:
                return success if custody_state(record) == "gone" else "outcome_unknown"
            if _wait_gone(record, wait_seconds):
                return success
    except PermissionError:
        return "failed"
    except (OSError, ValueError, TypeError, subprocess.SubprocessError):
        return "outcome_unknown"
    return "outcome_unknown"


def bind_process_group(record: Mapping[str, Any]) -> dict[str, Any]:
    """Resolve an anchor's group before any peer record can stop its leader."""
    payload = dict(record)
    pid = payload.get("pid") or payload.get("anchor_pid")
    started = payload.get("process_start_time") or payload.get("anchor_start_time")
    if not payload.get("process_group_id") and isinstance(pid, int) and started:
        try:
            payload.update(capture_group(pid, started))
        except (OSError, ValueError, subprocess.SubprocessError):
            pass
    return payload
