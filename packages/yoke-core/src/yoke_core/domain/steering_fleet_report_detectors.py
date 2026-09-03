"""Detect steering failures that arrive as silence in live control-plane state.

Queries reveal unregistered launches, frozen Monitor waiters, and merged
work lacking close-out. Launches corrected after delivery live in
:mod:`steering_fleet_report_abandoned`. Stuck delivery lives in
:mod:`steering_fleet_report_starvation`; dead waits that need judgment live
in :mod:`steering_fleet_report_dead_waits`.

Shared timestamp parsing stays here. Data comes from
``session_message_recipients``, ``session_launches``, and ``items``.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Sequence

from yoke_core.domain import db_backend
from yoke_core.domain.conflict_survey_declared_paths import TERMINAL_STATUSES
from yoke_core.domain.item_ref_render import render_item_refs
from yoke_core.domain.session_launch_delivery_state import IN_FLIGHT_LAUNCH_STATES
from yoke_core.domain.steering_fleet_report_evidence import (
    evidence_int,
    evidence_text,
)
from yoke_core.domain.session_launch_visibility import CORRELATION_FAILURE_CODES


def marker(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def parse_stamp(raw: str) -> datetime:
    parsed = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def age_seconds(stamp: str | None, now: str) -> int | None:
    """Seconds between ``stamp`` and ``now``, or ``None`` for no stamp."""
    if not stamp:
        return None
    return max(0, int((parse_stamp(now) - parse_stamp(stamp)).total_seconds()))


def suspected_orphaned_waiters(
    conn: Any,
    *,
    idle: Sequence[Any],
) -> tuple[Any, ...]:
    """Idle holders matching the Monitor-freeze signature.

    Membership in ``idle`` establishes that ``last_tool_call_at`` is past the
    report's idle threshold. The remaining facts already live on the session
    and its completed tool-call events; no waiter registry is inferred.
    """
    p = marker(conn)
    matches = []
    for holder in idle:
        row = conn.execute(
            f"""SELECT s.turn_posture,
                       (SELECT e.tool_name
                          FROM events e
                         WHERE e.session_id = s.session_id
                           AND e.event_name = 'HarnessToolCallCompleted'
                           AND e.tool_name IS NOT NULL
                           AND e.tool_name <> ''
                         ORDER BY e.created_at DESC, e.id DESC
                         LIMIT 1) AS last_completed_tool
                  FROM harness_sessions s
                 WHERE s.session_id = {p}""",
            (holder.session_id,),
        ).fetchone()
        if row is None:
            continue
        record = dict(row)
        if (
            str(record.get("turn_posture") or "") == "waiting"
            and str(record.get("last_completed_tool") or "") == "Monitor"
        ):
            matches.append(holder)
    return tuple(matches)


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


@dataclass(frozen=True)
class LandedItem:
    """One item whose branch landed while the item stayed open."""

    item_id: int
    public_ref: str
    status: str
    landed_at: str
    landed_seconds: int


def landed_recovery(public_ref: str) -> str:
    """The close-out recipe both the text and the machine projection print."""
    return (
        f"finish close-out with `yoke merge item {public_ref}`; do not wait on status"
    )


def unregistered_launches(
    conn: Any,
    *,
    project_id: int,
    now: str,
) -> tuple[UnregisteredLaunch, ...]:
    """Launches whose instruction is stranded by missing session binding.

    Correlation failures and exact registered-but-unbound sessions are visible
    immediately. Other in-flight launches appear only after their deadline.
    Closed unrelated history remains excluded.
    """
    p = marker(conn)
    states = sorted(IN_FLIGHT_LAUNCH_STATES)
    state_holes = ", ".join(p for _ in states)
    failures = sorted(CORRELATION_FAILURE_CODES)
    failure_holes = ", ".join(p for _ in failures)
    rows = conn.execute(
        f"""SELECT l.launch_id, l.selected_surface, l.requested_surface,
                   l.assigned_machine_id, l.requested_machine_id, l.state,
                   l.deadline_at, l.result_code, l.native_session_id,
                   l.native_launch_pid, l.native_launch_phase, l.spawn_duration_ms,
                   l.result_evidence,
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
               AND (l.state IN ({state_holes})
                    OR l.result_code IN ({failure_holes})
                    OR s.session_id IS NOT NULL)
             ORDER BY l.deadline_at ASC, l.launch_id ASC""",
        (int(project_id), *states, *failures),
    ).fetchall()
    gaps = []
    for row in rows:
        record = dict(row)
        elapsed = age_seconds(str(record.get("deadline_at") or ""), now) or 0
        result_code = str(record.get("result_code") or "")
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
                    str(record.get("native_launch_phase") or "") or None
                ),
                spawn_duration_ms=record.get("spawn_duration_ms"),
                native_stderr_tail=evidence_text(
                    record.get("result_evidence"), "native_stderr_tail"
                ),
                exit_code=evidence_int(record.get("result_evidence"), "exit_code"),
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


def landed_without_closeout(
    conn: Any,
    *,
    project_id: int,
    now: str,
) -> tuple[LandedItem, ...]:
    """Items whose branch landed while the item never reached a terminal status.

    The landing stamp is the item's own ``merged_at`` or, on a merge-queue
    project, ``merge_queue_landed_at``; the earlier of the two present is the
    moment the code was on the base branch.
    """
    p = marker(conn)
    terminal = sorted(TERMINAL_STATUSES)
    holes = ", ".join(p for _ in terminal)
    rows = conn.execute(
        f"""SELECT id, status, merged_at, merge_queue_landed_at
              FROM items
             WHERE project_id = {p}
               AND status NOT IN ({holes})
               AND (merged_at IS NOT NULL OR merge_queue_landed_at IS NOT NULL)""",
        (int(project_id), *terminal),
    ).fetchall()
    records = [dict(row) for row in rows]
    refs = render_item_refs(conn, [int(record["id"]) for record in records])
    landed = []
    for record in records:
        present = [
            str(record.get(name) or "")
            for name in ("merged_at", "merge_queue_landed_at")
            if record.get(name)
        ]
        if not present:
            continue
        landed_at = min(present)
        item_id = int(record["id"])
        landed.append(
            LandedItem(
                item_id=item_id,
                public_ref=refs.get(item_id, str(item_id)),
                status=str(record.get("status") or ""),
                landed_at=landed_at,
                landed_seconds=age_seconds(landed_at, now) or 0,
            )
        )
    return tuple(
        sorted(landed, key=lambda entry: (-entry.landed_seconds, entry.item_id))
    )


__all__ = [
    "LandedItem",
    "UnregisteredLaunch",
    "age_seconds",
    "landed_without_closeout",
    "marker",
    "parse_stamp",
    "suspected_orphaned_waiters",
    "unregistered_launches",
]
