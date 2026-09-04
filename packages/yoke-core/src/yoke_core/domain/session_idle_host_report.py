"""Answer a machine's idle-host question and record the hosts it reclaimed.

A machine's relay can see that a Claude host is idle but cannot tell
whether the Yoke session behind it has ended: a quiet row looks the same
whether the worker finished days ago or is sleeping through a transient
disconnect. So it asks. This module answers only for sessions the machine
runs, in projects the relay is authorized for, and the answer is the one
fact the row holds — ``ended_at`` or ``terminated_at`` is set — never an
inference from heartbeat age.

The same report carries what the relay already reclaimed: each host it
stopped or signalled, with pid, age, and resident size. Those land as
events keyed to the session so the steering report can show what memory
came back and why.
"""

from __future__ import annotations

from typing import Any, Dict, Iterable, List, Mapping, Sequence

from yoke_core.domain import db_backend
from yoke_core.domain.session_message_types import row_dict, timestamp, utc_now


#: Event recording one native host a machine stopped or signalled.
EVENT_NATIVE_HOST_RECLAIMED = "HarnessSessionNativeHostReclaimed"
SESSION_LIVE_STATUS = "session_live"

_SESSION_COLUMNS = "session_id, project_id, machine_id, ended_at, terminated_at"


def _p(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def _session_row(conn: Any, session_id: str) -> Dict[str, Any] | None:
    row = conn.execute(
        f"SELECT {_SESSION_COLUMNS} FROM harness_sessions WHERE session_id = {_p(conn)}",
        (session_id,),
    ).fetchone()
    return None if row is None else row_dict(row)


def _skip_reason(
    row: Dict[str, Any] | None,
    *,
    machine_id: str,
    authorized_projects: Sequence[int],
) -> str | None:
    if row is None:
        return "session_not_found"
    if str(row.get("machine_id") or "") != machine_id:
        return "machine_mismatch"
    project_id = row.get("project_id")
    if project_id is None or int(project_id) not in set(authorized_projects):
        return "project_unauthorized"
    return None


def _emit_reclaimed(
    conn: Any,
    session_id: str,
    *,
    machine_id: str,
    entry: Mapping[str, Any],
    observed_at: str,
) -> None:
    from yoke_core.domain.events import emit_event

    emit_event(
        EVENT_NATIVE_HOST_RECLAIMED,
        event_kind="system",
        event_type="session_lifecycle",
        source_type="backend",
        session_id=session_id,
        context={
            "session_id": session_id,
            "machine_id": machine_id,
            "observed_at": observed_at,
            "source": "relay_idle_host_reclaim",
            **{key: value for key, value in entry.items() if key != "session_id"},
        },
        conn=conn,
    )


def apply_idle_host_report(
    conn: Any,
    *,
    machine_id: str,
    authorized_projects: Iterable[int],
    hosts: Iterable[Mapping[str, Any]],
    reclaimed: Iterable[Mapping[str, Any]],
) -> Dict[str, Any]:
    """Name the ended sessions among ``hosts``; record every ``reclaimed`` host.

    Every host that is not answered ``ended`` comes back with a named status,
    because a silent omission here reads exactly like a live session — and a
    live session is the one thing the relay must leave alone.
    """
    projects = tuple(sorted({int(value) for value in authorized_projects}))
    observed_at = timestamp(utc_now())
    ended: List[str] = []
    skipped: List[Dict[str, Any]] = []
    recorded: List[str] = []
    for host in hosts:
        session_id = str(host.get("session_id") or "").strip()
        if not session_id:
            continue
        row = _session_row(conn, session_id)
        status = _skip_reason(row, machine_id=machine_id, authorized_projects=projects)
        if status is None and row is not None:
            if row.get("ended_at") or row.get("terminated_at"):
                ended.append(session_id)
                continue
            status = SESSION_LIVE_STATUS
        skipped.append({"session_id": session_id, "status": status})
    for entry in reclaimed:
        session_id = str(entry.get("session_id") or "").strip()
        if not session_id:
            continue
        row = _session_row(conn, session_id)
        status = _skip_reason(row, machine_id=machine_id, authorized_projects=projects)
        if status is not None:
            skipped.append({"session_id": session_id, "status": status})
            continue
        _emit_reclaimed(
            conn,
            session_id,
            machine_id=machine_id,
            entry=entry,
            observed_at=observed_at,
        )
        recorded.append(session_id)
    return {"ended": ended, "skipped": skipped, "recorded": recorded}


__all__ = [
    "EVENT_NATIVE_HOST_RECLAIMED",
    "SESSION_LIVE_STATUS",
    "apply_idle_host_report",
]
