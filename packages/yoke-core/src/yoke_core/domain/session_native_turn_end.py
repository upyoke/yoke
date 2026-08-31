"""Reclassify a session whose native ended its turn without saying so.

The wake router picks its operation from posture and liveness, and for one
surface both readings can be wrong at once. A ``codex-cli`` turn that ends
on a vendor error — the observed one was "Selected model is at capacity" —
leaves the CLI process alive and fires no ``Stop`` hook, though Codex
configures one and fires it on an ordinary ending. So posture stays
``running`` while the turn is over, liveness ages from ``active`` to
``stale``, and every wake for that session resolves
``message_active`` or ``message_idle``: two operations ``codex-cli`` does
not support. The envelope records ``skipped_operation`` and nothing else
ever happens. One session sat unreachable for fifty minutes holding its
item claim, silent to hook delivery and to the native resume both.

The one route that surface *does* support is the stopped-session resume,
and posture is what selects it. The native's own turn record says whether
the turn is really over, so the fix is to read that record and stamp the
posture the missing hook would have stamped. Nothing downstream changes:
``waiting`` already routes to ``message_stopped``.

Only the machine that ran the native can read that record, so this module
owns the two halves the control plane holds. :func:`probe_targets` names
the sessions whose wake is demonstrably stuck — read from the recorded
skip, so the probe only ever runs in a path that has already failed, never
against a healthy session. :func:`apply_native_turn_ends` applies what the
machine read back, on the machine's authority over its own sessions and
nobody else's.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, Iterable, List, Mapping, Sequence

from yoke_contracts.session_control.native_turn_end import (
    NATIVE_TURN_END_POSTURE,
    NATIVE_TURN_RECORD_SURFACES,
)
from yoke_core.domain import db_backend
from yoke_core.domain.session_message_types import (
    parse_timestamp,
    row_dict,
    timestamp,
    utc_now,
)
from yoke_core.domain.session_turn_posture import stamp_turn_posture


#: Event recording one session reclassified from its native turn record.
EVENT_SESSION_TURN_END_OBSERVED = "HarnessSessionTurnEndObserved"

#: Most sessions a single poll asks one machine to read back. A machine
#: with more stuck sessions than this gets the rest on its next poll; the
#: cap keeps one degraded machine from turning a poll into a file sweep.
MAX_PROBE_TARGETS = 25

_SESSION_COLUMNS = (
    "session_id, project_id, machine_id, executor_surface, turn_posture, "
    "ended_at, terminated_at"
)


def _p(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def probe_targets(
    conn: Any,
    *,
    machine_id: str,
    authorized_projects: Iterable[int],
    now: datetime | None = None,
) -> List[Dict[str, str]]:
    """Name this machine's sessions whose wake is stuck on a stale posture.

    The recorded skip is the trigger and the whole gate: a session appears
    here only once an envelope for it has already waited out its grace,
    been considered for a wake, and been refused for want of a supported
    operation. A healthy session never has such a row, so it is never read
    back — there is no sweep, no schedule, and no cost until something has
    already failed.
    """
    projects = tuple(sorted({int(value) for value in authorized_projects}))
    if not projects or not machine_id:
        return []
    marker = _p(conn)
    project_slots = ",".join(marker for _ in projects)
    surface_slots = ",".join(marker for _ in NATIVE_TURN_RECORD_SURFACES)
    rows = conn.execute(
        "SELECT DISTINCT hs.session_id,hs.executor_surface "
        "FROM harness_sessions hs "
        "JOIN session_message_recipients r ON r.session_id=hs.session_id "
        "AND r.state='pending' "
        "JOIN session_messages m ON m.message_id=r.message_id "
        f"AND m.cancelled_at IS NULL AND m.expires_at>{marker} "
        "JOIN session_message_attempts a ON a.target_session_id=hs.session_id "
        "AND a.message_id=r.message_id AND a.attempt_kind='wake_relay' "
        "AND a.result_code='skipped_operation' "
        f"WHERE hs.machine_id={marker} AND hs.ended_at IS NULL "
        f"AND hs.terminated_at IS NULL AND hs.turn_posture<>{marker} "
        f"AND hs.executor_surface IN ({surface_slots}) "
        f"AND hs.project_id IN ({project_slots}) "
        "ORDER BY hs.session_id",
        (
            timestamp(now or utc_now()),
            machine_id,
            NATIVE_TURN_END_POSTURE,
            *NATIVE_TURN_RECORD_SURFACES,
            *projects,
        ),
    ).fetchall()
    return [
        {
            "session_id": str(entry["session_id"]),
            "executor_surface": str(entry["executor_surface"]),
        }
        for entry in (row_dict(raw) for raw in rows)
    ][:MAX_PROBE_TARGETS]


def _session_row(conn: Any, session_id: str) -> Dict[str, Any] | None:
    marker = _p(conn)
    row = conn.execute(
        f"SELECT {_SESSION_COLUMNS} FROM harness_sessions WHERE session_id={marker}",
        (session_id,),
    ).fetchone()
    return None if row is None else row_dict(row)


def _skip_reason(
    row: Dict[str, Any] | None,
    *,
    machine_id: str,
    authorized_projects: Sequence[int],
) -> str | None:
    """Name why a reported turn end must not be applied, or ``None`` to apply."""
    if row is None:
        return "session_not_found"
    if str(row.get("machine_id") or "") != machine_id:
        return "machine_mismatch"
    project_id = row.get("project_id")
    if project_id is None or int(project_id) not in set(authorized_projects):
        return "project_unauthorized"
    if str(row.get("executor_surface") or "") not in NATIVE_TURN_RECORD_SURFACES:
        # Every other surface's turn end stamps itself, so a report about
        # one is evidence from the wrong place.
        return "surface_without_turn_record"
    if row.get("ended_at") or row.get("terminated_at"):
        return "session_terminal"
    return None


def _emit_observed(
    conn: Any,
    session_id: str,
    *,
    evidence: Mapping[str, Any],
    observed_at: str,
) -> None:
    from yoke_core.domain.events import emit_event

    emit_event(
        EVENT_SESSION_TURN_END_OBSERVED,
        event_kind="system",
        event_type="session_lifecycle",
        source_type="backend",
        session_id=session_id,
        context={
            "session_id": session_id,
            "observed_at": observed_at,
            "posture": NATIVE_TURN_END_POSTURE,
            "source": "relay_native_turn_record",
            **dict(evidence),
        },
        conn=conn,
    )


def apply_native_turn_ends(
    conn: Any,
    *,
    machine_id: str,
    authorized_projects: Iterable[int],
    reports: Iterable[Mapping[str, Any]],
    now: datetime | None = None,
) -> Dict[str, Any]:
    """Apply one machine's observed turn ends and name every refusal.

    Stamping is ordered against every other posture observation by the
    record's own timestamp, so a session that took a real turn after the
    error keeps the newer ``running`` and is left alone. Anything not
    applied comes back with a named status: a silent no-op here reads
    exactly like the stuck session this path exists to free.
    """
    current = now or utc_now()
    projects = tuple(sorted({int(value) for value in authorized_projects}))
    reclassified: List[str] = []
    skipped: List[Dict[str, Any]] = []
    for report in reports:
        session_id = str(report.get("session_id") or "").strip()
        if not session_id:
            continue
        row = _session_row(conn, session_id)
        status = _skip_reason(row, machine_id=machine_id, authorized_projects=projects)
        if status is None:
            observed_at = str(report.get("observed_at") or "")
            stamped = stamp_turn_posture(
                conn,
                session_id=session_id,
                posture=NATIVE_TURN_END_POSTURE,
                observed_at=parse_timestamp(observed_at) or current,
            )
            if not stamped:
                # A newer posture observation already won, which means the
                # session took a turn after the record this report read.
                status = "posture_superseded"
            else:
                _emit_observed(
                    conn,
                    session_id,
                    evidence=report.get("evidence") or {},
                    observed_at=observed_at,
                )
        if status is None:
            reclassified.append(session_id)
        else:
            skipped.append({"session_id": session_id, "status": status})
    return {"reclassified": reclassified, "skipped": skipped}


__all__ = [
    "EVENT_SESSION_TURN_END_OBSERVED",
    "MAX_PROBE_TARGETS",
    "apply_native_turn_ends",
    "probe_targets",
]
