"""Detect steering failures that arrive as silence in live control-plane state.

Queries reveal unregistered launches and frozen Monitor waiters. Merged work
lacking close-out lives in :mod:`steering_fleet_report_landed_open`, which
asks a release-custody question of its own. Launches corrected after delivery
live in :mod:`steering_fleet_report_abandoned`. Undelivered mail lives in
:mod:`steering_fleet_report_undelivered`; dead waits that need judgment live
in :mod:`steering_fleet_report_dead_waits`.

Shared timestamp parsing stays here. Data comes from
``session_message_recipients``, ``session_launches``, and ``items``.
"""

from __future__ import annotations

from yoke_contracts.timestamps import parse_instant

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Mapping, Sequence

from yoke_contracts.session_control.evidence import redacted_evidence_document
from yoke_core.domain import db_backend
from yoke_core.domain.item_terminal_resources import item_is_terminal
from yoke_core.domain.item_ref_resolution import resolve_item_ref_or_none
from yoke_core.domain.session_launch_assignment import assignment_ref
from yoke_core.domain.session_launch_delivery_state import (
    IN_FLIGHT_LAUNCH_STATES,
    QUEUED_LAUNCH_STATES,
)
from yoke_core.domain.steering_fleet_report_evidence import (
    evidence_document,
    evidence_int,
    evidence_text,
)
from yoke_core.domain.session_launch_visibility import (
    CORRELATION_FAILURE_CODES,
    LAUNCH_EXECUTION_FAILURE_CODES,
)
from yoke_core.domain.session_tool_call_projections import (
    LAST_COMPLETED_TOOL_COLUMN,
    MONITOR_TOOL_NAME,
    last_completed_tool_select,
)


def marker(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def parse_stamp(raw: datetime | str | None) -> datetime | None:
    return parse_instant(raw) if raw is not None else None


def age_seconds(stamp: datetime | str | None, now: datetime | str) -> int | None:
    """Seconds between ``stamp`` and ``now``, or ``None`` for no stamp."""
    current = parse_instant(now)
    instant = parse_stamp(stamp)
    if instant is None:
        return None
    return max(0, int((current - instant).total_seconds()))


def suspected_orphaned_waiters(
    conn: Any,
    *,
    idle: Sequence[Any],
) -> tuple[Any, ...]:
    """Idle holders matching the Monitor-freeze signature.

    Membership in ``idle`` establishes that ``last_tool_call_at`` is past
    the report's idle threshold. The remaining facts already live on the
    session row and its own tool-call rows, which is where this reads them
    — telemetry expiry would otherwise clear the signature and quietly
    stop reporting a frozen waiter. No waiter registry is inferred.
    """
    if not idle:
        return ()
    p = marker(conn)
    ids = tuple(dict.fromkeys(holder.session_id for holder in idle))
    rows = conn.execute(
        f"SELECT s.session_id, s.turn_posture {last_completed_tool_select(conn, session_alias='s')} "
        f"FROM harness_sessions s WHERE s.session_id IN ({','.join(p for _ in ids)})",
        ids,
    ).fetchall()
    matches = {
        str(row["session_id"])
        for row in rows
        if str(row["turn_posture"] or "") == "waiting"
        and str(row[LAST_COMPLETED_TOOL_COLUMN] or "") == MONITOR_TOOL_NAME
    }
    return tuple(holder for holder in idle if holder.session_id in matches)


def _recorded_diagnostic(value: Any) -> str:
    """Return the diagnostic reference a stored result evidence document names."""
    from yoke_contracts.session_control.evidence import (
        valid_native_diagnostic_reference,
    )
    from yoke_core.domain import json_helper

    try:
        document = json_helper.loads_text(str(value or "{}"))
    except (TypeError, ValueError):
        return ""
    if not isinstance(document, Mapping):
        return ""
    return (
        valid_native_diagnostic_reference(document.get("native_diagnostic_ref")) or ""
    )


@dataclass(frozen=True)
class UnregisteredLaunch:
    """One launch whose missing session binding blocks instruction delivery."""

    launch_id: str
    surface: str
    machine_id: str
    state: str
    overdue_seconds: int
    result_code: str = ""
    native_session_id: str | None = None
    observed_session_id: str | None = None
    native_launch_pid: int | None = None
    native_launch_phase: str | None = None
    spawn_duration_ms: int | None = None
    #: The last line the native itself said. A capture lives only on the
    #: machine that produced it, so a seat elsewhere reads the reason here
    #: or reads nothing.
    native_stderr_tail: str = ""
    exit_code: int | None = None
    #: The diagnostic reference this launch's own result recorded, so the
    #: row names the exact capture on the machine that produced it.
    evidence_id: str = ""
    detail: str | None = None


def unregistered_launches(
    conn: Any,
    *,
    project_id: int,
    now: str,
) -> tuple[UnregisteredLaunch, ...]:
    """Launches whose instruction is stranded by missing session binding.

    Correlation failures and exact registered-but-unbound sessions are visible
    immediately. Other in-flight launches appear only after their deadline;
    a launch still queued for pickup has not started its deadline window.
    Closed unrelated history remains excluded.
    """
    p = marker(conn)
    states = sorted(IN_FLIGHT_LAUNCH_STATES)
    state_holes = ", ".join(p for _ in states)
    failures = sorted(CORRELATION_FAILURE_CODES | LAUNCH_EXECUTION_FAILURE_CODES)
    failure_holes = ", ".join(p for _ in failures)
    rows = conn.execute(
        f"""SELECT l.launch_id, l.selected_surface, l.requested_surface,
                   l.assigned_machine_id, l.requested_machine_id, l.state,
                   l.deadline_at, l.result_code, l.native_session_id,
                   l.native_launch_pid, l.native_launch_phase, l.spawn_duration_ms,
                   l.result_evidence, l.session_name, l.created_at,
                   s.session_id AS observed_session_id
              FROM session_launches l
              LEFT JOIN harness_sessions s
                ON s.session_id = l.native_session_id
               AND s.project_id = l.project_id
               AND s.executor_surface = l.selected_surface
               AND (l.assigned_machine_id IS NULL
                    OR s.machine_id = l.assigned_machine_id)
               AND s.ended_at IS NULL
               AND s.terminated_at IS NULL
             WHERE l.registered_session_id IS NULL
               AND l.project_id = {p}
               AND l.state <> 'cancelled'
               AND (l.state IN ({state_holes})
                    OR l.result_code IN ({failure_holes})
                    OR s.session_id IS NOT NULL)
             ORDER BY l.deadline_at ASC, l.launch_id ASC""",
        (int(project_id), *states, *failures),
    ).fetchall()
    gaps = []
    for row in rows:
        record = dict(row)
        reference = assignment_ref(record.get("session_name"))
        item_id = (
            resolve_item_ref_or_none(conn, reference, project=project_id)
            if reference
            else None
        )
        if item_id is not None:
            if item_is_terminal(conn, item_id) is True:
                continue
            replacement = conn.execute(
                "SELECT 1 FROM session_launches "
                f"WHERE project_id={p} AND session_name LIKE {p} "
                f"AND created_at>{p} AND registered_session_id IS NOT NULL LIMIT 1",
                (project_id, f"{reference}: %", record["created_at"]),
            ).fetchone()
            if replacement is not None:
                continue
        queued = record.get("state") in QUEUED_LAUNCH_STATES
        elapsed = 0 if queued else age_seconds(record.get("deadline_at"), now) or 0
        result_code = str(record.get("result_code") or "")
        evidence = redacted_evidence_document(
            evidence_document(record.get("result_evidence"))
        )
        detail = evidence.get("probe_detail")
        observed_session_id = str(record.get("observed_session_id") or "") or None
        if not elapsed and result_code not in failures and not observed_session_id:
            continue
        gaps.append(
            UnregisteredLaunch(
                launch_id=str(record["launch_id"]),
                surface=str(
                    record.get("selected_surface")
                    or record.get("requested_surface")
                    or "unknown"
                ),
                machine_id=str(
                    record.get("assigned_machine_id")
                    or record.get("requested_machine_id")
                    or "unassigned"
                ),
                state=str(record.get("state") or ""),
                overdue_seconds=elapsed,
                result_code=result_code,
                native_session_id=(str(record.get("native_session_id") or "") or None),
                observed_session_id=observed_session_id,
                native_launch_pid=record.get("native_launch_pid"),
                native_launch_phase=(
                    "native_exited"
                    if evidence.get("native_exit_at")
                    else str(record.get("native_launch_phase") or "") or None
                ),
                spawn_duration_ms=record.get("spawn_duration_ms"),
                native_stderr_tail=evidence_text(
                    record.get("result_evidence"), "native_stderr_tail"
                ),
                exit_code=evidence_int(record.get("result_evidence"), "exit_code"),
                evidence_id=_recorded_diagnostic(record.get("result_evidence")),
                detail=str(detail) if detail else None,
            )
        )
    return tuple(
        sorted(
            gaps,
            key=lambda entry: (
                0 if entry.result_code in failures or entry.observed_session_id else 1,
                -entry.overdue_seconds,
                entry.launch_id,
            ),
        )
    )


__all__ = [
    "UnregisteredLaunch",
    "age_seconds",
    "marker",
    "parse_stamp",
    "suspected_orphaned_waiters",
    "unregistered_launches",
]
