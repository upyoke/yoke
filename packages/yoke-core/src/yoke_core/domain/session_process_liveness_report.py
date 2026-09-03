"""Apply one machine's verified native-process death reports.

A local process record proves only that the recorded process is gone.  It
does not revoke control-plane authority.  A stale session with no holdings
can end immediately; one with any current holding remains live, keeps every
claim, and carries the process-gone observation until new activity supersedes
it or a deliberate/holdings-TTL teardown ends it.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Mapping, Sequence

from yoke_contracts.session_control.liveness import LIVENESS_STALE
from yoke_core.domain.session_message_routing import session_liveness
from yoke_core.domain.session_message_types import row_dict
from yoke_core.domain.session_native_process_observation import (
    CLAIMS_HELD_STATUS,
    record_native_process_gone,
)
from yoke_core.domain.sessions_analytics import SessionError
from yoke_core.domain.sessions_holdings_projection import session_holdings_by_session
from yoke_core.domain.sessions_render_end import end_session


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
    if row is None:
        return "session_not_found"
    if str(row.get("machine_id") or "") != machine_id:
        return "machine_mismatch"
    project_id = row.get("project_id")
    if project_id is None or int(project_id) not in set(authorized_projects):
        return "project_unauthorized"
    liveness = session_liveness(row, now=now)
    if liveness != LIVENESS_STALE:
        return f"liveness_{liveness}"
    return None


def _end_claimless(
    conn: Any,
    session_id: str,
    evidence: Mapping[str, Any],
) -> str | None:
    try:
        end_session(
            conn,
            session_id,
            release_claims=False,
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


def apply_verified_process_death_reports(
    conn: Any,
    *,
    machine_id: str,
    authorized_projects: Iterable[int],
    reports: Iterable[Mapping[str, Any]],
    now: datetime | None = None,
) -> Dict[str, Any]:
    """End claimless dead processes and retain every claim-holding session."""
    current = now or datetime.now(timezone.utc)
    projects = tuple(sorted({int(value) for value in authorized_projects}))
    holdings = session_holdings_by_session(conn, previous_limit=0)
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
        )
        evidence = report.get("evidence") or {}
        current_holdings = (holdings.get(session_id) or {}).get("current") or []
        if status is None and current_holdings:
            record_native_process_gone(conn, session_id, evidence, observed_at=current)
            status = CLAIMS_HELD_STATUS
        if status is None:
            status = _end_claimless(conn, session_id, evidence)
        if status is None:
            ended.append(session_id)
        else:
            skipped.append({"session_id": session_id, "status": status})
    return {"ended": ended, "skipped": skipped}


__all__ = [
    "PROCESS_VERIFIED_DEAD_REASON",
    "apply_verified_process_death_reports",
]
