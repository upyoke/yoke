"""Machine-local containment for unregistered launches and detached resumes.

Creating a native and registering it are two separate events, and the gap
between them is where an unattended agent does damage. Natives that never
registered have read the backlog, adopted briefs assigned to other sessions,
and written into the shared checkout with no claim and no lane — nothing was
holding them, because the launch that started them had already been written
off by the time anyone noticed.

Containment closes that gap without a control-plane round trip. The relay
records the process it started; registration itself clears the record, since
the launch handoff is delivered only once a native has registered and pulled
its message. A record that outlives the registration deadline therefore names
a process that is running without authority, and the sweep terminates it.

Detached resumes use the same owner-only record family. Hook activity refreshes
their custody timestamp; the sweep reaps only sustained inactivity or an
absolute runaway, never a healthy turn merely because one relay cycle ended.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import signal
import time
from typing import Iterator, Mapping
from uuid import UUID

from yoke_contracts.organization_contract.fleet_keys import FLEET_KEY_SPECS
from yoke_contracts.process_ancestry import process_start_time
from yoke_contracts.session_control.resume import (
    RESUME_ATTEMPT_ENV,
    RESUME_INACTIVITY_SECONDS,
    RESUME_RUNAWAY_SECONDS,
)
from yoke_cli.config import machine_config


SUPERVISION_DIRECTORY_NAME = "session-launch-supervision"

# A native is contained only after the launch could no longer register, plus
# a margin so the sweep never races the deadline it is backing up.
CONTAINMENT_GRACE_SECONDS = 120
CONTAINMENT_TTL_SECONDS = (
    int(FLEET_KEY_SPECS["fleet.launch_deadline_minutes"].default) * 60
    + CONTAINMENT_GRACE_SECONDS
)
_TERMINATE_WAIT_SECONDS = 2.0
_MAX_RECORD_BYTES = 4096


@dataclass(frozen=True)
class ContainmentOutcome:
    """What the sweep did with one supervised native."""

    launch_id: str
    pid: int
    result: str
    native_session_id: str | None = None
    supervision_kind: str = "launch"
    reason: str = "registration_timeout"


def _directory(state_dir: Path | None = None) -> Path:
    root = state_dir or machine_config.cache_dir()
    directory = root / SUPERVISION_DIRECTORY_NAME
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    return directory


def _record_path(launch_id: str, state_dir: Path | None = None) -> Path:
    return _directory(state_dir) / f"{launch_id}.json"


def record_supervised_native(
    launch_id: str,
    pid: int,
    *,
    native_session_id: str | None = None,
    supervision_kind: str = "launch",
    capture_path: Path | None = None,
    state_dir: Path | None = None,
    now: float | None = None,
) -> bool:
    """Record one native under a launch or resume-attempt identifier.

    Launch registration remains best effort. Detached resume callers require
    this custody record and stop the process when it cannot be written.
    """
    if not launch_id or pid <= 0 or supervision_kind not in {"launch", "resume"}:
        return False
    start_time = process_start_time(pid)
    if not start_time:
        return False
    payload = {
        "launch_id": launch_id,
        "pid": int(pid),
        "process_start_time": start_time,
        "native_session_id": native_session_id or None,
        "supervision_kind": supervision_kind,
        "last_activity_at": int(time.time() if now is None else now),
        "capture_path": str(capture_path) if capture_path is not None else None,
        "recorded_at": int(time.time() if now is None else now),
    }
    try:
        path = _record_path(launch_id, state_dir)
        temporary = path.with_suffix(f".{os.getpid()}.tmp")
        temporary.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
        temporary.chmod(0o600)
        os.replace(temporary, path)
    except OSError:
        return False
    return True


def touch_supervised_resume(
    attempt_id: str,
    *,
    state_dir: Path | None = None,
    now: float | None = None,
) -> bool:
    """Refresh local custody after one hook from a detached resume."""
    try:
        UUID(attempt_id)
        path = _record_path(attempt_id, state_dir)
        if path.stat().st_size > _MAX_RECORD_BYTES:
            return False
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict) or payload.get("supervision_kind") != "resume":
            return False
        payload["last_activity_at"] = int(time.time() if now is None else now)
        temporary = path.with_suffix(f".{os.getpid()}.tmp")
        temporary.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
        temporary.chmod(0o600)
        os.replace(temporary, path)
    except (OSError, TypeError, ValueError):
        return False
    return True


def touch_supervised_resume_from_environment(
    *,
    environ: Mapping[str, str] | None = None,
    state_dir: Path | None = None,
    now: float | None = None,
) -> bool:
    """Refresh resume custody when a native hook inherited its attempt id."""
    source = os.environ if environ is None else environ
    attempt_id = str(source.get(RESUME_ATTEMPT_ENV) or "").strip()
    return bool(
        attempt_id and touch_supervised_resume(attempt_id, state_dir=state_dir, now=now)
    )


def release_supervised_native(
    launch_id: str,
    *,
    state_dir: Path | None = None,
) -> None:
    """Stop supervising ``launch_id`` — its native proved it registered."""
    if not launch_id:
        return
    try:
        _record_path(launch_id, state_dir).unlink(missing_ok=True)
    except OSError:
        return


def _records(state_dir: Path | None) -> Iterator[tuple[Path, dict[str, object]]]:
    try:
        entries = sorted(_directory(state_dir).glob("*.json"))
    except OSError:
        return
    for path in entries:
        try:
            if path.stat().st_size > _MAX_RECORD_BYTES:
                continue
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(payload, dict):
            yield path, payload


def _terminate(pid: int) -> str:
    """Signal the native's whole process group, escalating only if it stays."""
    try:
        group = os.getpgid(pid)
    except OSError:
        return "already_exited"
    try:
        os.killpg(group, signal.SIGTERM)
    except OSError:
        return "already_exited"
    deadline = time.monotonic() + _TERMINATE_WAIT_SECONDS
    while time.monotonic() < deadline:
        try:
            os.killpg(group, 0)
        except OSError:
            return "terminated"
        time.sleep(0.1)
    try:
        os.killpg(group, signal.SIGKILL)
    except OSError:
        return "terminated"
    return "killed"


def contain_stranded_launch_natives(
    *,
    state_dir: Path | None = None,
    now: float | None = None,
    ttl_seconds: int = CONTAINMENT_TTL_SECONDS,
) -> list[ContainmentOutcome]:
    """Contain launches past registration and resumes past custody limits."""
    current = time.time() if now is None else now
    outcomes: list[ContainmentOutcome] = []
    for path, payload in _records(state_dir):
        recorded_at = payload.get("recorded_at")
        if not isinstance(recorded_at, int):
            continue
        kind = str(payload.get("supervision_kind") or "launch")
        if kind not in {"launch", "resume"}:
            kind = "launch"
        reason = "registration_timeout"
        if kind == "resume":
            activity_at = payload.get("last_activity_at")
            last_activity = float(activity_at) if isinstance(activity_at, int) else 0.0
            capture_path = payload.get("capture_path")
            if isinstance(capture_path, str) and capture_path:
                try:
                    last_activity = max(
                        last_activity, Path(capture_path).stat().st_mtime
                    )
                except OSError:
                    pass
            runaway = current - recorded_at >= RESUME_RUNAWAY_SECONDS
            inactive = current - last_activity >= RESUME_INACTIVITY_SECONDS
            if not runaway and not inactive:
                continue
            reason = "runaway" if runaway else "inactivity"
        elif current - recorded_at < ttl_seconds:
            continue
        launch_id = str(payload.get("launch_id") or path.stem)
        pid = payload.get("pid")
        native_session_id = payload.get("native_session_id")
        if not isinstance(pid, int) or pid <= 0:
            _drop(path)
            continue
        # A reused pid names a different process entirely; the native this
        # record was written for is already gone.
        if process_start_time(pid) != payload.get("process_start_time"):
            result = "already_exited"
        else:
            result = _terminate(pid)
        _drop(path)
        outcomes.append(
            ContainmentOutcome(
                launch_id=launch_id,
                pid=pid,
                result=result,
                native_session_id=(
                    str(native_session_id) if native_session_id else None
                ),
                supervision_kind=kind,
                reason=reason,
            )
        )
    return outcomes


def _drop(path: Path) -> None:
    try:
        path.unlink(missing_ok=True)
    except OSError:
        return


__all__ = [
    "CONTAINMENT_GRACE_SECONDS",
    "CONTAINMENT_TTL_SECONDS",
    "SUPERVISION_DIRECTORY_NAME",
    "ContainmentOutcome",
    "contain_stranded_launch_natives",
    "record_supervised_native",
    "release_supervised_native",
    "touch_supervised_resume",
    "touch_supervised_resume_from_environment",
]
