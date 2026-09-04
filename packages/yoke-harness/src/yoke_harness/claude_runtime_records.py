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

from dataclasses import dataclass
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
SESSION_RECORD_RESOLVED = "session_record_resolved"
SESSION_RECORD_MISSING = "session_record_missing"
SESSION_RECORD_INVALID = "session_record_invalid"
SESSION_RECORD_RECOVERY = {
    SESSION_RECORD_MISSING: (
        "Restore Claude's per-pid record and run `claude stop <job-id>` "
        "from it; never signal a daemon-owned host directly."
    ),
    SESSION_RECORD_INVALID: (
        "Have Claude rewrite its per-pid record, then run `claude stop "
        "<job-id>` from it; never signal a daemon-owned host directly."
    ),
}


@dataclass(frozen=True)
class ClaudeSessionRecordResolution:
    """One bounded per-pid record resolution, including a named refusal."""

    result_code: str
    pid: int | None = None
    record: dict[str, Any] | None = None

    @property
    def recovery(self) -> str:
        return SESSION_RECORD_RECOVERY.get(self.result_code, "")


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


def _resolve_session_pid(pid: int, root: Path) -> ClaudeSessionRecordResolution:
    path = root / CLAUDE_SESSIONS_DIR_NAME / f"{pid}.json"
    try:
        details = path.lstat()
    except FileNotFoundError:
        return ClaudeSessionRecordResolution(SESSION_RECORD_MISSING, pid=pid)
    except OSError:
        return ClaudeSessionRecordResolution(SESSION_RECORD_INVALID, pid=pid)
    if not stat.S_ISREG(details.st_mode):
        return ClaudeSessionRecordResolution(SESSION_RECORD_INVALID, pid=pid)
    raw = bounded_json_record(path)
    started = raw.get("startedAt") if raw is not None else None
    if (
        raw is None
        or raw.get("pid") != pid
        or not str(raw.get("sessionId") or "")
        or not str(raw.get("kind") or "")
        or not str(raw.get("jobId") or "")
        or not isinstance(started, (int, float))
        or isinstance(started, bool)
    ):
        return ClaudeSessionRecordResolution(SESSION_RECORD_INVALID, pid=pid)
    return ClaudeSessionRecordResolution(
        SESSION_RECORD_RESOLVED,
        pid=pid,
        record={
            "session_id": str(raw["sessionId"]),
            "kind": str(raw["kind"]),
            "job_id": str(raw["jobId"]),
            "started_epoch": started / 1000.0,
        },
    )


def resolve_claude_session_record(
    *,
    pid: int | None = None,
    session_id: str | None = None,
    root: Path | None = None,
) -> ClaudeSessionRecordResolution:
    """Resolve Claude's per-pid record by its pid or native session id."""
    if (pid is None) == (session_id is None):
        raise ValueError("provide exactly one of pid or session_id")
    base = root if root is not None else claude_config_root()
    if pid is not None:
        return _resolve_session_pid(int(pid), base)
    target = str(session_id or "")
    invalid: list[int] = []
    valid_count = 0
    matches: list[ClaudeSessionRecordResolution] = []
    try:
        candidates = sorted((base / CLAUDE_SESSIONS_DIR_NAME).glob("*.json"))
    except OSError:
        candidates = []
    for path in candidates:
        try:
            candidate_pid = int(path.stem)
        except ValueError:
            continue
        resolution = _resolve_session_pid(candidate_pid, base)
        if resolution.result_code == SESSION_RECORD_INVALID:
            invalid.append(candidate_pid)
            continue
        if resolution.record is None:
            continue
        valid_count += 1
        if resolution.record["session_id"] == target:
            matches.append(resolution)
    if matches:
        return max(
            matches,
            key=lambda entry: (float(entry.record["started_epoch"]), entry.pid or 0),
        )
    if invalid and valid_count == 0:
        return ClaudeSessionRecordResolution(
            SESSION_RECORD_INVALID,
            pid=invalid[0] if len(invalid) == 1 else None,
        )
    return ClaudeSessionRecordResolution(SESSION_RECORD_MISSING)


def claude_session_record(pid: int, root: Path | None = None) -> dict[str, Any] | None:
    """Return the normalized record projection used by idle-host discovery."""
    return resolve_claude_session_record(pid=pid, root=root).record


__all__ = [
    "CLAUDE_CONFIG_DIR_ENV",
    "CLAUDE_JOBS_DIR_NAME",
    "CLAUDE_JOB_STATE_FILE_NAME",
    "CLAUDE_SESSIONS_DIR_NAME",
    "MAX_CLAUDE_RECORD_BYTES",
    "SESSION_RECORD_INVALID",
    "SESSION_RECORD_MISSING",
    "SESSION_RECORD_RESOLVED",
    "ClaudeSessionRecordResolution",
    "bounded_json_record",
    "claude_config_root",
    "claude_job_state",
    "claude_session_record",
    "job_state_path",
    "resolve_claude_session_record",
]
