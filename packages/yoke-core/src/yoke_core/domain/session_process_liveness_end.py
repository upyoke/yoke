"""End sessions whose machine proved their native process is gone.

A session row keeps reading ``active`` until its heartbeat ages past the
stale TTL, and keeps reading ``stale`` — never ``ended`` — until the
periodic cleanup sweep reaches it. For a native that actually died, both
readings are lies with consequences: the wake machinery offers a stale
session the idle-injection route, which pokes a process that no longer
exists, so every wake for it fails until the sweep's much longer holdings
TTL expires. One observed cursor worker died at 12:46Z and its row stayed
running, holding claims, for hours.

Only the machine that ran the native can settle the question, and it
already runs one relay. The relay reports the sessions whose recorded pid
is verifiably gone; this module applies that report. Ending the row moves
it to the ``ended`` liveness whose wake operation is a fresh native
resume, which is exactly the recovery a dead process needs.

The report is evidence, not authority: a reported session is ended only
when it belongs to the reporting machine, sits in a project that relay is
authorized for, and is already past the short stale TTL. Anything else is
skipped with a named status, and the cleanup sweep remains the backstop.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Mapping, Sequence

from .session_message_routing import session_liveness
from .session_message_types import row_dict
from .sessions_analytics import SessionError
from .sessions_render_end import end_session
from yoke_contracts.session_control.liveness import LIVENESS_STALE


#: The end reason recorded on ``HarnessSessionEnded`` for this path.
PROCESS_VERIFIED_DEAD_REASON = "process_verified_dead"

_SESSION_COLUMNS = (
    "session_id, project_id, machine_id, executor, last_heartbeat, "
    "last_tool_call_at, ended_at, terminated_at"
)


def _session_row(conn: Any, session_id: str) -> Dict[str, Any] | None:
    row = conn.execute(
        f"SELECT {_SESSION_COLUMNS} FROM harness_sessions WHERE session_id = %s",
        (session_id,),
    ).fetchone()
    return None if row is None else row_dict(row)


def _skip_reason(
    row: Dict[str, Any] | None,
    *,
    machine_id: str,
    authorized_projects: Sequence[int],
    now: datetime,
) -> str | None:
    """Name why a reported session must not be ended, or ``None`` to end it."""
    if row is None:
        return "session_not_found"
    if str(row.get("machine_id") or "") != machine_id:
        return "machine_mismatch"
    project_id = row.get("project_id")
    if project_id is None or int(project_id) not in set(authorized_projects):
        return "project_unauthorized"
    liveness = session_liveness(row, now=now)
    if liveness != LIVENESS_STALE:
        # ``active`` means the row has been touched since the process died —
        # a re-registration, a resumed episode — and ``ended``/``terminated``
        # is already the outcome this path exists to reach.
        return f"liveness_{liveness}"
    return None


def _end_one(
    conn: Any,
    session_id: str,
    evidence: Mapping[str, Any],
) -> str | None:
    """End one verified-dead session; return a skip status on refusal."""
    try:
        end_session(
            conn,
            session_id,
            release_claims=False,
            # A dead process cannot take the next chain step, so a pending
            # checkpoint is exactly what the resume this end enables must
            # pick up. The override records the rationale on the ledger.
            override_chain_end=True,
            chain_end_rationale=PROCESS_VERIFIED_DEAD_REASON,
            end_reason=PROCESS_VERIFIED_DEAD_REASON,
            agent_presence_evidence={
                "source": "relay_process_probe",
                "verdict": PROCESS_VERIFIED_DEAD_REASON,
                **dict(evidence),
            },
        )
    except SessionError as exc:
        return f"refused_{exc.code.lower()}"
    return None


def end_process_verified_dead_sessions(
    conn: Any,
    *,
    machine_id: str,
    authorized_projects: Iterable[int],
    reports: Iterable[Mapping[str, Any]],
    now: datetime | None = None,
) -> Dict[str, Any]:
    """Apply one machine's verified-dead session reports.

    Returns the ended session ids and, for every report left alone, the
    named status that explains it — a silent no-op here would be
    indistinguishable from the ghost this path exists to remove.
    """
    current = now or datetime.now(timezone.utc)
    projects = tuple(sorted({int(value) for value in authorized_projects}))
    ended: List[str] = []
    skipped: List[Dict[str, Any]] = []
    for report in reports:
        session_id = str(report.get("session_id") or "").strip()
        if not session_id:
            continue
        status = _skip_reason(
            _session_row(conn, session_id),
            machine_id=machine_id,
            authorized_projects=projects,
            now=current,
        ) or _end_one(conn, session_id, report.get("evidence") or {})
        if status is None:
            ended.append(session_id)
        else:
            skipped.append({"session_id": session_id, "status": status})
    return {"ended": ended, "skipped": skipped}


__all__ = [
    "PROCESS_VERIFIED_DEAD_REASON",
    "end_process_verified_dead_sessions",
]
