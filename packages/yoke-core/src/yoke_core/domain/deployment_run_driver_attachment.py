"""Which process is driving a deployment run, and whether it is still live.

A self-deploy freeze can run for minutes before the wrapper claims a
capture or the pipeline writes status=executing. During that window the
run still reads as ``created``, a second execute starts, and a tail on
the printed capture blames missing flags. The attachment on the run row
is the fact those readers share: who is driving, since when, which
phase, and which capture they will write. A second driver for a live
attachment refuses by name. Re-drive of an interrupted driver still
works — a stale heartbeat is not live, and neither is a recorded pid the
driver's own machine reports gone: only that machine can see its process
table, so its re-drive names the exited pid and supersedes it at once, while a
driver on another machine is still judged by its heartbeat alone.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from yoke_contracts.timestamps import as_utc, format_instant, parse_instant, utc_now
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

#: Error code a relayed attach or release carries when the run row was busy.
#: The caller skips the tick and reports the named reason rather than retrying.
ROW_LOCK_BUSY_CODE = "driver_row_lock_busy"

#: Error code an attach carries when a live driver already holds the run. Its
#: result names that driver, so a caller on the same machine can check its pid.
DRIVER_ALREADY_ATTACHED_CODE = "driver_already_attached"


@dataclass(frozen=True)
class DriverAttachment:
    """Live or last-known driver recorded on one run."""

    run_id: str
    session_id: str
    pid: int
    attached_at: datetime
    heartbeat_at: datetime
    phase: str
    progress_capture: str
    machine_id: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "attached_at", as_utc(self.attached_at))
        object.__setattr__(self, "heartbeat_at", as_utc(self.heartbeat_at))

    def as_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "session_id": self.session_id,
            "pid": self.pid,
            "attached_at": format_instant(self.attached_at),
            "heartbeat_at": format_instant(self.heartbeat_at),
            "phase": self.phase,
            "progress_capture": self.progress_capture,
            "machine_id": self.machine_id,
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
        f"{format_instant(current.attached_at)}, phase {current.phase}{capture}. "
        "Wait for that driver to finish or stop it; do not start a second "
        "one. An interrupted driver is recovered by re-driving this same "
        "run id: from the machine it ran on, as soon as that process is gone; "
        "from any other machine, once its heartbeat is ten minutes old."
    )


def is_live(attachment: DriverAttachment, *, now: datetime) -> bool:
    """True at the inclusive native heartbeat window boundary."""
    current = as_utc(now)
    return current - attachment.heartbeat_at <= LIVE_HEARTBEAT


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
        attached_at=parse_instant(payload.get("attached_at")),
        heartbeat_at=parse_instant(payload.get("heartbeat_at")),
        phase=str(payload.get("phase") or ""),
        progress_capture=str(payload.get("progress_capture") or ""),
        machine_id=str(payload.get("machine_id") or ""),
    )


def _serialize(attachment: DriverAttachment) -> str:
    return dumps_compact(
        {
            "session_id": attachment.session_id,
            "pid": attachment.pid,
            "attached_at": format_instant(attachment.attached_at),
            "heartbeat_at": format_instant(attachment.heartbeat_at),
            "phase": attachment.phase,
            "progress_capture": attachment.progress_capture,
            "machine_id": attachment.machine_id,
        }
    )


def _column_ready(conn: Any) -> bool:
    return _column_exists(conn, "deployment_runs", COLUMN)


def _locked_row(conn: Any, run_id_value: str) -> tuple[str, Any] | None:
    """Lock the run row without waiting, so a liveness write can never queue.

    Raises :class:`DeploymentRunRowLockBusy` when another transaction holds the
    row. Attaching and releasing are both liveness bookkeeping: a tick that
    waits stops reporting, and a release that waits keeps the process alive
    through its own shutdown.
    """
    from yoke_core.domain.deployment_runs_lock import lock_run_bounded

    status = lock_run_bounded(conn, run_id_value)
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
    machine_id: str = "",
    exited_driver_pid: int = 0,
    now: datetime | None = None,
) -> DriverAttachment | None:
    """Record this process as the run's driver, or refuse a live other one.

    ``None`` means the additive column has not converged; the caller
    proceeds. Same pid+session refreshes heartbeat and phase.
    ``exited_driver_pid`` is the caller's word that the recorded driver's pid
    is gone from *machine_id*; it supersedes a live attachment only when both
    match what the attachment recorded, since no other machine can know.

    Raises :class:`DeploymentRunRowLockBusy` rather than waiting for a run row
    another transaction holds -- see :func:`_locked_row`.
    """
    if phase not in VALID_PHASES:
        raise ValueError(f"driver phase {phase!r} is not registered")
    clock = utc_now() if now is None else as_utc(now)
    locked = _locked_row(conn, run_id_value)
    if locked is None:
        raise LookupError(f"deployment run {run_id_value!r} not found")
    if not _column_ready(conn):
        return None
    current = parse_attachment(run_id_value, locked[1])
    same = (
        current is not None and current.session_id == session_id and current.pid == pid
    )
    exited = (
        current is not None
        and bool(machine_id)
        and current.machine_id == machine_id
        and current.pid == exited_driver_pid
    )
    if current is not None and is_live(current, now=clock) and not (same or exited):
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
        machine_id=machine_id.strip(),
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
    """Clear the attachment when this process still holds it.

    Raises :class:`DeploymentRunRowLockBusy` rather than waiting, so shutdown
    always completes: a release that blocked on the run row is what left a
    SIGTERMed watcher alive in its own cleanup.
    """
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
    conn: Any, *, run_id_value: str, now: datetime
) -> DriverAttachment | None:
    """Return the live driver on *run_id_value*, or None."""
    now = as_utc(now)
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
    conn: Any, *, progress_capture: str, now: datetime
) -> DriverAttachment | None:
    """Return the live driver that claimed *progress_capture*, or None."""
    now = as_utc(now)
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
    "ROW_LOCK_BUSY_CODE",
    "COLUMN",
    "DRIVER_ALREADY_ATTACHED_CODE",
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
