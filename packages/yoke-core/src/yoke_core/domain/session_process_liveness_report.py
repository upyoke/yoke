"""Apply one machine's verified native-process death reports.

A local process record proves only that the recorded process is gone.  It
does not revoke control-plane authority.  A session with nothing outstanding
can end immediately; one that still holds something, declared a wait about
itself, or is owed an answer remains live, keeps every claim, and carries the
process-gone observation until new activity supersedes it or a
deliberate/holdings-TTL teardown ends it.

The staleness TTL exists because quiet has two causes the control plane
cannot tell apart, and it waits out the ambiguity.  A report naming the
launch that started the process carries no ambiguity to wait out: the machine
started that native, kept its pid and start time, and is reporting that the
pid is no longer that process.  Waiting the TTL out anyway is what left a
finished worker's row open for twenty-three minutes until a person killed it
by hand.  So a launch-named report ends its session on the poll that observed
the exit, and only a report with no launch behind it -- an anchor a hook
happened to write for some session -- still waits for the TTL to agree.

Correcting the launch behind a dead native is separate from ending its
session, and runs whatever the session verdict is. A session that died a
minute ago still reads active, so waiting for it to go stale is exactly how a
launch kept reporting ``succeeded`` for a worker that was already gone.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Mapping, Sequence

from yoke_contracts.session_control.liveness import LIVENESS_ENDED, LIVENESS_STALE
from yoke_core.domain.session_launch_abandonment import (
    settle_and_notify_native_death,
)
from yoke_core.domain.session_message_routing import session_liveness
from yoke_core.domain.session_message_store import cancel_open_recipients
from yoke_core.domain.session_message_types import row_dict
from yoke_core.domain.session_mode import session_is_parked
from yoke_core.domain.session_native_process_observation import (
    AWAITING_SEAT_REPLY_STATUS,
    CLAIMS_HELD_STATUS,
    PARKED_STATUS,
    record_native_process_gone,
)
from yoke_core.domain.sessions_analytics import SessionError
from yoke_core.domain.sessions_holdings_projection import session_holdings_by_session
from yoke_core.domain.sessions_render_end import end_session
from yoke_core.domain.steering_message_recipients import session_awaiting_seat_reply


PROCESS_VERIFIED_DEAD_REASON = "process_verified_dead"

_SESSION_COLUMNS = (
    "session_id, project_id, machine_id, executor, mode, last_heartbeat, "
    "last_tool_call_at, ended_at, terminated_at"
)


def _session_row(conn: Any, session_id: str) -> Dict[str, Any] | None:
    row = conn.execute(
        f"SELECT {_SESSION_COLUMNS} FROM harness_sessions WHERE session_id = %s",
        (session_id,),
    ).fetchone()
    return None if row is None else row_dict(row)


def _launch_named(evidence: Mapping[str, Any]) -> bool:
    """Whether the machine's own launch custody record is behind this report."""
    return bool(str(evidence.get("launch_id") or "").strip())


def _skip_reason(
    row: Dict[str, Any] | None,
    *,
    machine_id: str,
    authorized_projects: Sequence[int],
    now: datetime,
    launch_named: bool,
) -> str | None:
    if row is None:
        return "session_not_found"
    if str(row.get("machine_id") or "") != machine_id:
        return "machine_mismatch"
    project_id = row.get("project_id")
    if project_id is None or int(project_id) not in set(authorized_projects):
        return "project_unauthorized"
    liveness = session_liveness(row, now=now)
    if liveness == LIVENESS_ENDED:
        return f"liveness_{liveness}"
    if liveness != LIVENESS_STALE and not launch_named:
        return f"liveness_{liveness}"
    return None


def _retention_reason(
    conn: Any,
    row: Dict[str, Any],
    *,
    holdings: Sequence[Any],
) -> str | None:
    """Why this proven-dead session's row must survive, or ``None`` to end it."""
    if holdings:
        return CLAIMS_HELD_STATUS
    if session_is_parked(row.get("mode")):
        return PARKED_STATUS
    if session_awaiting_seat_reply(conn, str(row["session_id"])) is not None:
        return AWAITING_SEAT_REPLY_STATUS
    return None


def _end_claimless(
    conn: Any,
    session_id: str,
    evidence: Mapping[str, Any],
    *,
    now: datetime,
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
    # Nothing will read this session's inbox again, so its senders are told
    # now rather than left waiting on a delivery that cannot happen.
    cancel_open_recipients(
        conn,
        session_id=session_id,
        cancelled_at=now,
        result_code=PROCESS_VERIFIED_DEAD_REASON,
    )
    return None


def apply_verified_process_death_reports(
    conn: Any,
    *,
    machine_id: str,
    authorized_projects: Iterable[int],
    reports: Iterable[Mapping[str, Any]],
    now: datetime | None = None,
) -> Dict[str, Any]:
    """End settled dead processes and retain every session still owed to."""
    current = now or datetime.now(timezone.utc)
    projects = tuple(sorted({int(value) for value in authorized_projects}))
    holdings = session_holdings_by_session(conn, previous_limit=0)
    ended: List[str] = []
    corrected: List[str] = []
    skipped: List[Dict[str, Any]] = []
    for report in reports:
        session_id = str(report.get("session_id") or "").strip()
        if not session_id:
            continue
        evidence = report.get("evidence") or {}
        row = _session_row(conn, session_id)
        status = _skip_reason(
            row,
            machine_id=machine_id,
            authorized_projects=projects,
            now=current,
            launch_named=_launch_named(evidence),
        )
        if settle_and_notify_native_death(conn, session_id, evidence) is not None:
            corrected.append(session_id)
        if status is None and row is not None:
            status = _retention_reason(
                conn,
                row,
                holdings=(holdings.get(session_id) or {}).get("current") or [],
            )
            if status is not None:
                record_native_process_gone(
                    conn, session_id, evidence, observed_at=current
                )
        if status is None:
            status = _end_claimless(conn, session_id, evidence, now=current)
        if status is None:
            ended.append(session_id)
        else:
            skipped.append({"session_id": session_id, "status": status})
    return {"ended": ended, "launches_corrected": corrected, "skipped": skipped}


__all__ = [
    "PROCESS_VERIFIED_DEAD_REASON",
    "apply_verified_process_death_reports",
]
