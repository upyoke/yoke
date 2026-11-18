"""Durable PID and creation-time custody for native process trees.

Captured descendants retain custody after their supervisor exits. Every stop
revalidates each incarnation through the shared platform process owner.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Callable, Mapping

from yoke_contracts import platform_process
from yoke_contracts.owner_private_path import write_owner_private

MAX_RECORD_BYTES = 4096
TERMINATE_WAIT_SECONDS = 2.0
SUCCESS_RESULTS = frozenset({"terminated", "killed", "already_exited"})


def _identity(record: Mapping[str, Any]) -> tuple[int, str]:
    pid = record.get("pid") or record.get("anchor_pid")
    started = record.get("process_start_time") or record.get("anchor_start_time")
    if not isinstance(pid, int) or pid <= 0 or not started:
        raise ValueError("process_identity_missing")
    return pid, str(started)


def _members(record: Mapping[str, Any]) -> dict[str, str]:
    pid, started = _identity(record)
    return {str(pid): started, **dict(record.get("process_members") or {})}


def capture_process_tree(pid: int, started: str) -> dict[str, Any]:
    """Capture a verified root and its current descendants for later recovery."""
    handle = platform_process.handle_from_pid(pid, float(started))
    if handle is None:
        raise OSError("process_identity_changed")
    return {"process_members": {str(p): str(stamp) for p, stamp in handle.members}}


def _capture_live_members(members: dict[str, str]) -> dict[str, str]:
    """Add live members' current descendants; a member exiting meanwhile adds none."""
    for pid, started in tuple(members.items()):
        handle = platform_process.handle_from_pid(int(pid), float(started))
        if handle is not None:
            members.update({str(p): str(stamp) for p, stamp in handle.members})
    return members


def custody_state(
    record: Mapping[str, Any],
    *,
    start_time_of: Callable[[int], str | None] | None = None,
) -> str:
    """Return live, gone or unresolved; an observation failure proves no exit."""
    try:
        members = _members(record)
        if start_time_of is not None and not record.get("process_members"):
            pid, started = _identity(record)
            return "live" if start_time_of(pid) == started else "gone"
        return "live" if any(
            platform_process.pid_alive(int(pid), float(started))
            for pid, started in members.items()
        ) else "gone"
    except (OSError, ValueError, TypeError):
        return "unresolved"


def write_record(path: Path, record: Mapping[str, Any]) -> bool:
    """Atomically write an owner-private custody record; report failure as False."""
    body = json.dumps(dict(record), sort_keys=True)
    if len(body.encode()) > MAX_RECORD_BYTES:
        return False
    try:
        write_owner_private(path, body)
    except OSError:
        return False
    return True


def terminate_record(
    record: dict[str, Any],
    *,
    wait_seconds: float = TERMINATE_WAIT_SECONDS,
    persist: Callable[[Mapping[str, Any]], bool] | None = None,
) -> str:
    """Persist survivors before asking the platform owner to stop their trees."""
    state = custody_state(record)
    if state == "gone":
        return "already_exited"
    if state != "live":
        return "outcome_unknown"
    try:
        members = _capture_live_members(_members(record))
        protected = {os.getpid(), *(entry.pid for entry in
                                   platform_process.ancestors(os.getpid()))}
        if any(int(pid) in protected and platform_process.pid_alive(int(pid), float(started))
               for pid, started in members.items()):
            return "shared_process_group"
        record["process_members"] = members
        if persist is not None and not persist(record):
            return "outcome_unknown"
        pid, started = _identity(record)
        handle = platform_process.GroupHandle.from_record({
            "pid": pid, "start_time": float(started),
            "members": [[int(p), float(stamp)] for p, stamp in members.items()],
        })
        platform_process.stop_group(handle, wait_seconds)
        return "terminated" if custody_state(record) == "gone" else "outcome_unknown"
    except PermissionError:
        return "failed"
    except (OSError, ValueError, TypeError):
        return "outcome_unknown"


def bind_process_tree(record: Mapping[str, Any]) -> dict[str, Any]:
    """Capture every live record before stopping any overlapping supervisor."""
    payload = dict(record)
    try:
        payload["process_members"] = _capture_live_members(_members(payload))
    except (OSError, ValueError, TypeError):
        pass
    return payload
