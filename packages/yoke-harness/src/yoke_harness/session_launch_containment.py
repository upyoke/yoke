"""Machine-local custody records for launched natives and detached resumes.

Creating a native and registering it are two separate events, and the gap
between them is where an unattended agent does damage. Natives that never
registered have read the backlog, adopted briefs assigned to other sessions,
and written into the shared checkout with no claim and no lane — nothing was
holding them, because the launch that started them had already been written
off by the time anyone noticed.

This module owns the record itself: the relay writes one for every native it
starts, hooks refresh it, and delivering the launch instruction removes it,
because a native that read its mandate has registered and is no longer running
without authority. What is done with a live record belongs elsewhere —
:mod:`session_launch_containment_sweep` terminates the ones naming a process
that never registered, and :mod:`session_relay_resume_settlement` settles the
resumes among them. Watching a launched native after it registers is the
launch handle's job, in :mod:`session_relay_termination`.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import time
from typing import Iterator, Mapping
from uuid import UUID

from yoke_contracts.process_ancestry import process_start_time
from yoke_contracts.session_control.resume import RESUME_ATTEMPT_ENV
from yoke_cli.config import machine_config


SUPERVISION_DIRECTORY_NAME = "session-launch-supervision"


MAX_RECORD_BYTES = 4096


def _directory(state_dir: Path | None = None) -> Path:
    root = state_dir or machine_config.cache_dir()
    directory = root / SUPERVISION_DIRECTORY_NAME
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    return directory


def supervision_record_path(launch_id: str, state_dir: Path | None = None) -> Path:
    return _directory(state_dir) / f"{launch_id}.json"


def record_supervised_native(
    launch_id: str,
    pid: int,
    *,
    native_session_id: str | None = None,
    supervision_kind: str = "launch",
    capture_path: Path | None = None,
    diagnostic_ref: str | None = None,
    lease_id: str | None = None,
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
        # The capture's own name, so a reader that has the record can name the
        # native's account without reconstructing where the file went.
        "diagnostic_ref": diagnostic_ref or None,
        # The attempt lease the relay leased this resume under. Settling the
        # attempt happens after the batch that started it has drained, so the
        # lease has to survive on disk or the outcome has nowhere to land.
        "lease_id": lease_id or None,
        "recorded_at": int(time.time() if now is None else now),
    }
    try:
        path = supervision_record_path(launch_id, state_dir)
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
        path = supervision_record_path(attempt_id, state_dir)
        if path.stat().st_size > MAX_RECORD_BYTES:
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
        supervision_record_path(launch_id, state_dir).unlink(missing_ok=True)
    except OSError:
        return


def supervised_records(
    state_dir: Path | None = None,
) -> Iterator[tuple[Path, dict[str, object]]]:
    """Yield every supervision record, for each reader to project itself."""
    try:
        entries = sorted(_directory(state_dir).glob("*.json"))
    except OSError:
        return
    for path in entries:
        try:
            if path.stat().st_size > MAX_RECORD_BYTES:
                continue
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(payload, dict):
            yield path, payload


__all__ = [
    "MAX_RECORD_BYTES",
    "supervision_record_path",
    "SUPERVISION_DIRECTORY_NAME",
    "record_supervised_native",
    "release_supervised_native",
    "supervised_records",
    "touch_supervised_resume",
    "touch_supervised_resume_from_environment",
]
