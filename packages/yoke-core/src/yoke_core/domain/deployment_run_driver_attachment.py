"""Which process is driving a deployment run, and whether it is still live.

A self-deploy freeze can run for minutes before the wrapper claims a
capture or the pipeline writes status=executing. During that window the
run still reads as ``created``, a second execute starts, and a tail on
the printed capture blames missing flags. The attachment on the run row
is the fact those readers share: who is driving, since when, which
phase, and which capture they will write. A second driver for a live
attachment refuses by name. Re-drive of an interrupted driver still
works — a stale heartbeat is not live.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from yoke_core.domain.db_helpers import iso8601_now
from yoke_core.domain.json_helper import dumps_compact, loads_text
from yoke_core.domain.schema_common import _column_exists


ATTACH_FUNCTION_ID = "deployment_runs.execution.attach_driver"
RELEASE_FUNCTION_ID = "deployment_runs.execution.release_driver"
FOR_CAPTURE_FUNCTION_ID = "deployment_runs.driver.for_capture"
COLUMN = "driver_attachment"
PHASE_FREEZING_SOURCE = "freezing_source"
PHASE_EXECUTING = "executing"
VALID_PHASES = frozenset({PHASE_FREEZING_SOURCE, PHASE_EXECUTING})
LIVE_HEARTBEAT = timedelta(seconds=600)


@dataclass(frozen=True)
class DriverAttachment:
    """Live or last-known driver recorded on one run."""

    run_id: str
    session_id: str
    pid: int
    attached_at: str
    heartbeat_at: str
    phase: str
    progress_capture: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "session_id": self.session_id,
            "pid": self.pid,
            "attached_at": self.attached_at,
            "heartbeat_at": self.heartbeat_at,
            "phase": self.phase,
            "progress_capture": self.progress_capture,
        }


class DriverAlreadyAttached(Exception):
    """A live driver already owns this run."""

    def __init__(self, run_id: str, current: DriverAttachment) -> None:
        self.run_id = run_id
        self.current = current
        super().__init__(format_refusal(run_id, current))


def format_refusal(run_id: str, current: DriverAttachment) -> str:
    """Named reason a second driver must not start."""
    capture = (
        f", writing {current.progress_capture}" if current.progress_capture else ""
    )
    return (
        f"deployment run {run_id} already has a live driver: session "
        f"{current.session_id}, pid {current.pid}, attached at "
        f"{current.attached_at}, phase {current.phase}{capture}. "
        "Wait for that driver to finish or stop it; do not start a second "
        "one. An interrupted driver is recovered by re-driving this same "
        "run id after that process is gone."
    )


def _parse_time(value: str) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed


def is_live(attachment: DriverAttachment, *, now: str) -> bool:
    """True when the recorded heartbeat is still inside the live window."""
    stamped = _parse_time(attachment.heartbeat_at)
    current = _parse_time(now)
    if stamped is None or current is None:
        return False
    return current - stamped <= LIVE_HEARTBEAT


def parse_attachment(run_id: str, raw: Any) -> DriverAttachment | None:
    """Return an attachment from the JSON column, or None when unset."""
    text = "" if raw is None else str(raw).strip()
    if not text:
        return None
    try:
        payload = loads_text(text)
    except (TypeError, ValueError):
        return None
    if not isinstance(payload, dict):
        return None
    try:
        pid = int(payload.get("pid") or 0)
    except (TypeError, ValueError):
        return None
    session_id = str(payload.get("session_id") or "").strip()
    if not session_id or pid <= 0:
        return None
    return DriverAttachment(
        run_id=run_id,
        session_id=session_id,
        pid=pid,
        attached_at=str(payload.get("attached_at") or ""),
        heartbeat_at=str(payload.get("heartbeat_at") or ""),
        phase=str(payload.get("phase") or ""),
        progress_capture=str(payload.get("progress_capture") or ""),
    )


def _serialize(attachment: DriverAttachment) -> str:
    return dumps_compact(
        {
            "session_id": attachment.session_id,
            "pid": attachment.pid,
            "attached_at": attachment.attached_at,
            "heartbeat_at": attachment.heartbeat_at,
            "phase": attachment.phase,
            "progress_capture": attachment.progress_capture,
        }
    )


def _column_ready(conn: Any) -> bool:
    return _column_exists(conn, "deployment_runs", COLUMN)


def _locked_row(conn: Any, run_id_value: str) -> tuple[str, Any] | None:
    from yoke_core.domain.deployment_runs_lock import lock_run

    status = lock_run(conn, run_id_value)
    if status is None:
        return None
    if not _column_ready(conn):
        return status, None
    row = conn.execute(
        f"SELECT {COLUMN} FROM deployment_runs WHERE id=%s",
        (run_id_value,),
    ).fetchone()
    raw = None if row is None else (row[COLUMN] if hasattr(row, "keys") else row[0])
    return status, raw


def attach_driver(
    conn: Any,
    run_id_value: str,
    *,
    session_id: str,
    pid: int,
    phase: str,
    progress_capture: str = "",
    now: str | None = None,
) -> DriverAttachment | None:
    """Record this process as the run's driver, or refuse a live other one.

    ``None`` means the additive column has not converged; the caller
    proceeds. Same pid+session refreshes heartbeat and phase.
    """
    if phase not in VALID_PHASES:
        raise ValueError(f"driver phase {phase!r} is not registered")
    clock = now or iso8601_now()
    locked = _locked_row(conn, run_id_value)
    if locked is None:
        raise LookupError(f"deployment run {run_id_value!r} not found")
    if not _column_ready(conn):
        return None
    current = parse_attachment(run_id_value, locked[1])
    same = (
        current is not None and current.session_id == session_id and current.pid == pid
    )
    if current is not None and is_live(current, now=clock) and not same:
        raise DriverAlreadyAttached(run_id_value, current)
    attached_at = current.attached_at if same and current is not None else clock
    recorded = DriverAttachment(
        run_id=run_id_value,
        session_id=session_id,
        pid=pid,
        attached_at=attached_at,
        heartbeat_at=clock,
        phase=phase,
        progress_capture=progress_capture.strip(),
    )
    conn.execute(
        f"UPDATE deployment_runs SET {COLUMN}=%s WHERE id=%s",
        (_serialize(recorded), run_id_value),
    )
    return recorded


def release_driver(
    conn: Any,
    run_id_value: str,
    *,
    session_id: str,
    pid: int,
) -> bool:
    """Clear the attachment when this process still holds it."""
    locked = _locked_row(conn, run_id_value)
    if locked is None or not _column_ready(conn):
        return False
    current = parse_attachment(run_id_value, locked[1])
    if current is None or current.session_id != session_id or current.pid != pid:
        return False
    conn.execute(
        f"UPDATE deployment_runs SET {COLUMN}=%s WHERE id=%s",
        ("", run_id_value),
    )
    return True


def live_attachment_for_run(
    conn: Any, *, run_id_value: str, now: str
) -> DriverAttachment | None:
    """Return the live driver on *run_id_value*, or None."""
    if not _column_ready(conn):
        return None
    row = conn.execute(
        f"SELECT {COLUMN} FROM deployment_runs WHERE id=%s",
        (run_id_value,),
    ).fetchone()
    if row is None:
        return None
    raw = row[COLUMN] if hasattr(row, "keys") else row[0]
    current = parse_attachment(run_id_value, raw)
    if current is None or not is_live(current, now=now):
        return None
    return current


def live_attachment_for_capture(
    conn: Any, *, progress_capture: str, now: str
) -> DriverAttachment | None:
    """Return the live driver that claimed *progress_capture*, or None."""
    wanted = str(progress_capture or "").strip()
    if not wanted or not _column_ready(conn):
        return None
    rows = conn.execute(
        f"SELECT id, {COLUMN} FROM deployment_runs "
        f"WHERE {COLUMN} IS NOT NULL AND {COLUMN} <> ''"
    ).fetchall()
    wanted_path = Path(wanted)
    for row in rows:
        run_id_value = str(row["id"] if hasattr(row, "keys") else row[0])
        raw = row[COLUMN] if hasattr(row, "keys") else row[1]
        current = parse_attachment(run_id_value, raw)
        if current is None or not is_live(current, now=now):
            continue
        stored = current.progress_capture
        if not stored:
            continue
        if stored == wanted:
            return current
        stored_path = Path(stored)
        if stored_path.name == wanted_path.name:
            try:
                if stored_path.resolve() == wanted_path.resolve():
                    return current
            except OSError:
                continue
    return None


__all__ = [
    "ATTACH_FUNCTION_ID",
    "COLUMN",
    "DriverAlreadyAttached",
    "DriverAttachment",
    "FOR_CAPTURE_FUNCTION_ID",
    "PHASE_EXECUTING",
    "PHASE_FREEZING_SOURCE",
    "RELEASE_FUNCTION_ID",
    "VALID_PHASES",
    "attach_driver",
    "format_refusal",
    "is_live",
    "live_attachment_for_capture",
    "live_attachment_for_run",
    "parse_attachment",
    "release_driver",
]
