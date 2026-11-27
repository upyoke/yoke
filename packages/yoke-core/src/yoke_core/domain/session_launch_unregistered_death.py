"""Retain native exit evidence and close a launch that never registered.

A launch waits ten minutes for a registration that may still arrive, because
silence has two causes the control plane cannot tell apart: a native that is
still coming up, and a native that is already gone. The machine that started
the native has no such ambiguity — it kept the pid and the start time, and it
watches the process itself. When that machine reports the process gone with
the launch still unregistered, waiting the deadline out adds nothing except
ten minutes during which the launch reads in-flight, the work reads staffed,
and the native's own account ages quietly on disk.

So a reported death closes the launch on the poll that observed it, with the
exit status and the capture reference the machine sent, and the ordinary
deadline stays exactly where it is for a process that is still alive.

An exit from the creating process does not settle the bound session's
liveness. The session-death path independently decides whether the session
ended and whether it ever worked.
"""

from __future__ import annotations

from yoke_contracts.timestamps import parse_instant

from datetime import datetime

from typing import Any, Dict, Iterable, List, Mapping

from yoke_contracts.session_control.launch_registration import (
    NATIVE_EXITED_UNREGISTERED_CODE,
)
from yoke_core.domain.session_launch_closure_evidence import (
    closure_evidence,
    sign_in_recovery,
)
from yoke_core.domain.session_launch_delivery_state import IN_FLIGHT_LAUNCH_STATES
from yoke_core.domain.db_savepoint import savepoint
from yoke_core.domain.session_launch_settlement import record_launch_native_exit
from yoke_core.domain.session_launch_store import (
    LAUNCH_COLUMNS,
    begin_mutation,
    marker,
    row_to_launch,
    update_launch,
    utc_now,
)
from yoke_core.domain.session_launch_types import LaunchRecord
from yoke_core.domain.session_relay_evidence import merge_redacted_evidence


CLOSURE_REASON = "native_exited_before_registering"
#: What the machine that watched the native can testify to. Every other key a
#: report carries is dropped rather than trusted onto the launch row.
_REPORTED_EVIDENCE_FIELDS = (
    "exit_code",
    "native_diagnostic_ref",
    "native_exit_at",
    "native_stderr_tail",
    "native_stderr_excerpt",
)


def _launch(conn: Any, launch_id: str) -> LaunchRecord | None:
    p = marker(conn)
    row = conn.execute(
        f"SELECT {LAUNCH_COLUMNS} FROM session_launches WHERE launch_id = {p}",
        (launch_id,),
    ).fetchone()
    return row_to_launch(row) if row is not None else None


def _skip_reason(
    launch: LaunchRecord | None,
    *,
    machine_id: str,
    authorized_projects: frozenset[int],
) -> str | None:
    """Why this reported launch must not be closed, or ``None`` to close it."""
    if launch is None:
        return "launch_not_found"
    if str(launch.assigned_machine_id or "") != machine_id:
        return "machine_mismatch"
    if int(launch.project_id) not in authorized_projects:
        return "project_unauthorized"
    if str(launch.registered_session_id or "").strip():
        return "registered"
    if launch.state not in IN_FLIGHT_LAUNCH_STATES:
        return "not_in_flight"
    return None


def _close(
    conn: Any,
    launch: LaunchRecord,
    evidence: Mapping[str, Any],
    *,
    now: datetime | str,
) -> None:
    recorded = closure_evidence(
        conn,
        launch=launch,
        result_code=NATIVE_EXITED_UNREGISTERED_CODE,
        closure_reason=CLOSURE_REASON,
        relay_id=launch.assigned_relay_id,
        machine_id=launch.assigned_machine_id,
        started_at=launch.awaiting_registration_at or launch.launching_at,
        now=now,
    )
    recorded.update(
        {name: evidence[name] for name in _REPORTED_EVIDENCE_FIELDS if name in evidence}
    )
    recovery = sign_in_recovery(launch)
    if recovery:
        recorded["sign_in_recovery"] = recovery
    update_launch(
        conn,
        launch.launch_id,
        delivery_changed_at=now,
        state="failed",
        native_launch_phase="native_exited",
        completed_at=now,
        result_code=NATIVE_EXITED_UNREGISTERED_CODE,
        result_evidence=merge_redacted_evidence(launch.result_evidence, recorded),
    )


def _record_bound_exit(
    conn: Any, launch: LaunchRecord, evidence: Mapping[str, Any]
) -> bool:
    """Require the assigned launch's process and a measured exit."""
    session_id = launch.registered_session_id
    reported_session = evidence.get("registered_session_id")
    exit_at = evidence.get("native_exit_at")
    if not session_id or (reported_session and reported_session != session_id):
        return False
    if type(evidence.get("native_pid")) is not int or not isinstance(exit_at, str):
        return False
    try:
        measured = parse_instant(exit_at)
    except ValueError:
        return False
    with savepoint(conn, "record_bound_native_exit", owns=False):
        return record_launch_native_exit(
            conn, session_id, {"launch_id": launch.launch_id, "native_pid": evidence["native_pid"]},
            exited_at=measured,
        )


def apply_unregistered_native_death_reports(
    conn: Any,
    *,
    machine_id: str,
    authorized_projects: Iterable[int],
    reports: Iterable[Mapping[str, Any]],
    now: datetime | str | None = None,
) -> Dict[str, Any]:
    """Close every reported launch this machine may close, naming the rest."""
    current = utc_now() if now is None else parse_instant(now)
    projects = frozenset(int(value) for value in authorized_projects)
    closed: List[str] = []
    skipped: List[Dict[str, str]] = []
    recorded_exits: List[str] = []
    begin_mutation(conn)
    for report in reports:
        launch_id = str(report.get("launch_id") or "").strip()
        if not launch_id:
            continue
        launch = _launch(conn, launch_id)
        status = _skip_reason(
            launch,
            machine_id=machine_id,
            authorized_projects=projects,
        )
        evidence = report.get("evidence") or {}
        if status == "registered" and launch is not None and _record_bound_exit(conn, launch, evidence):
            recorded_exits.append(launch_id)
            continue
        if status is not None or launch is None:
            skipped.append({"launch_id": launch_id, "status": status or "unknown"})
            continue
        _close(conn, launch, evidence, now=current)
        closed.append(launch_id)
    outcome = {"closed_launches": closed, "skipped_launches": skipped}
    if recorded_exits:
        outcome["recorded_native_exits"] = recorded_exits
    return outcome


__all__ = [
    "CLOSURE_REASON",
    "apply_unregistered_native_death_reports",
]
