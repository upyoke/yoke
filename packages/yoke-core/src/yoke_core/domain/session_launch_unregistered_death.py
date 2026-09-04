"""Close a launch whose native died before any session registered for it.

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

The registered half of this is deliberately elsewhere: a launch that bound a
session is corrected by :mod:`session_launch_abandonment` from the same poll's
session reports, which can also ask whether that session ever worked. Nothing
here has a session to ask about — that is the whole shape being closed.
"""

from __future__ import annotations

from typing import Any, Dict, Iterable, List, Mapping

from yoke_contracts.session_control.launch_registration import (
    NATIVE_EXITED_UNREGISTERED_CODE,
)
from yoke_core.domain.session_launch_closure_evidence import closure_evidence
from yoke_core.domain.session_launch_delivery_state import IN_FLIGHT_LAUNCH_STATES
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
        # A session did register, so this launch is the other path's to
        # correct: it can ask whether that session ever worked, and this
        # cannot.
        return "registered"
    if launch.state not in IN_FLIGHT_LAUNCH_STATES:
        return "not_in_flight"
    return None


def _close(
    conn: Any,
    launch: LaunchRecord,
    evidence: Mapping[str, Any],
    *,
    now: str,
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
    update_launch(
        conn,
        launch.launch_id,
        delivery_changed_at=now,
        state="failed",
        completed_at=now,
        result_code=NATIVE_EXITED_UNREGISTERED_CODE,
        result_evidence=merge_redacted_evidence(launch.result_evidence, recorded),
    )


def apply_unregistered_native_death_reports(
    conn: Any,
    *,
    machine_id: str,
    authorized_projects: Iterable[int],
    reports: Iterable[Mapping[str, Any]],
    now: str | None = None,
) -> Dict[str, Any]:
    """Close every reported launch this machine may close, naming the rest."""
    current = now or utc_now()
    projects = frozenset(int(value) for value in authorized_projects)
    closed: List[str] = []
    skipped: List[Dict[str, str]] = []
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
        if status is not None or launch is None:
            skipped.append({"launch_id": launch_id, "status": status or "unknown"})
            continue
        _close(conn, launch, report.get("evidence") or {}, now=current)
        closed.append(launch_id)
    return {"closed_launches": closed, "skipped_launches": skipped}


__all__ = [
    "CLOSURE_REASON",
    "apply_unregistered_native_death_reports",
]
