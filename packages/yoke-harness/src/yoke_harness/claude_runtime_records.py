"""Bounded reads of the records Claude Code keeps about its own sessions and jobs.

Claude Code writes two families of machine-local records this side reads
and never writes. ``sessions/<pid>.json`` exists per session process and
names the session, its background job, and when the process took the
session on. ``jobs/<job-id>/state.json`` exists per background job and
carries the daemon's own view of the job: its state, whether a turn is in
progress, and when that view last moved. Both live under the Claude config
root, ``CLAUDE_CONFIG_DIR`` when set and ``~/.claude`` otherwise.

Every read is bounded and refuses symlinks, oversized files, and anything
that is not a JSON object, because a hook or relay must never block or
crash on a file another program owns.
"""

from __future__ import annotations

from datetime import datetime
import json
import os
from pathlib import Path
import stat
from typing import Any


CLAUDE_CONFIG_DIR_ENV = "CLAUDE_CONFIG_DIR"
CLAUDE_SESSIONS_DIR_NAME = "sessions"
CLAUDE_JOBS_DIR_NAME = "jobs"
CLAUDE_JOB_STATE_FILE_NAME = "state.json"
MAX_CLAUDE_RECORD_BYTES = 64 * 1024


def claude_config_root() -> Path:
    configured = os.environ.get(CLAUDE_CONFIG_DIR_ENV, "").strip()
    return Path(configured).expanduser() if configured else Path.home() / ".claude"


def bounded_json_record(path: Path) -> dict[str, Any] | None:
    """Read one JSON object without following symlinks or unbounded files."""
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    descriptor: int | None = None
    try:
        descriptor = os.open(path, flags)
        details = os.fstat(descriptor)
        if (
            not stat.S_ISREG(details.st_mode)
            or details.st_size > MAX_CLAUDE_RECORD_BYTES
        ):
            return None
        raw = os.read(descriptor, MAX_CLAUDE_RECORD_BYTES + 1)
        if len(raw) > MAX_CLAUDE_RECORD_BYTES:
            return None
        decoded = json.loads(raw.decode("utf-8"))
        return decoded if isinstance(decoded, dict) else None
    except (OSError, UnicodeDecodeError, ValueError):
        return None
    finally:
        if descriptor is not None:
            os.close(descriptor)


def job_state_path(job_id: str, root: Path | None = None) -> Path:
    base = root if root is not None else claude_config_root()
    return base / CLAUDE_JOBS_DIR_NAME / job_id / CLAUDE_JOB_STATE_FILE_NAME


def _iso_epoch(value: Any) -> float | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def claude_job_state(job_id: str, root: Path | None = None) -> dict[str, Any] | None:
    """Return the daemon's view of one job: state, tempo, and when it last moved."""
    if not job_id or "/" in job_id or job_id.startswith("."):
        return None
    state = bounded_json_record(job_state_path(job_id, root))
    if state is None:
        return None
    return {
        "state": str(state.get("state") or ""),
        "tempo": str(state.get("tempo") or ""),
        "updated_epoch": _iso_epoch(state.get("updatedAt")),
    }


def claude_session_record(pid: int, root: Path | None = None) -> dict[str, Any] | None:
    """Return the session Claude recorded for one process, or nothing."""
    base = root if root is not None else claude_config_root()
    record = bounded_json_record(base / CLAUDE_SESSIONS_DIR_NAME / f"{int(pid)}.json")
    if record is None or record.get("pid") != int(pid):
        return None
    started = record.get("startedAt")
    return {
        "session_id": str(record.get("sessionId") or ""),
        "kind": str(record.get("kind") or ""),
        "job_id": str(record.get("jobId") or ""),
        "started_epoch": (
            started / 1000.0 if isinstance(started, (int, float)) else None
        ),
    }


__all__ = [
    "CLAUDE_CONFIG_DIR_ENV",
    "CLAUDE_JOBS_DIR_NAME",
    "CLAUDE_JOB_STATE_FILE_NAME",
    "CLAUDE_SESSIONS_DIR_NAME",
    "MAX_CLAUDE_RECORD_BYTES",
    "bounded_json_record",
    "claude_config_root",
    "claude_job_state",
    "claude_session_record",
    "job_state_path",
]
