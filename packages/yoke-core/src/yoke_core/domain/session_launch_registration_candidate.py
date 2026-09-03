"""Correlate supervised launches with sessions that register before listing."""

from __future__ import annotations

import time
from datetime import timedelta
from typing import Any, Callable, Mapping

from yoke_contracts.session_control.evidence import redacted_evidence_document
from yoke_contracts.session_control.launch_registration import (
    NATIVE_LAUNCH_WORKSPACE_FIELD,
    REGISTERED_BUT_UNBOUND_CODE,
    SPAWN_WORKSPACE_MISSING_CODE,
)
from yoke_core.domain import db_backend, json_helper
from yoke_core.domain.session_launch_store import (
    begin_mutation,
    get_launch,
    marker,
    parse_time,
    utc_now,
    value,
)
from yoke_core.domain.session_relay_evidence import merge_redacted_evidence


REGISTRATION_CANDIDATE_WAIT_SECONDS = 5.0
_REGISTRATION_POLL_SECONDS = 0.1
REGISTRATION_CANDIDATE_STATES = frozenset(
    {"launching", "awaiting_registration", "outcome_unknown"}
)


def registration_evidence_document(raw: Any) -> dict[str, str | int]:
    try:
        document = json_helper.loads_text(str(raw or "{}"))
    except (TypeError, ValueError):
        document = {}
    return redacted_evidence_document(
        document if isinstance(document, Mapping) else None
    )


def registration_binding_window(
    started_at: Any,
    deadline_at: Any,
    evidence: Mapping[str, object],
) -> tuple[str, str] | None:
    bound_seconds = evidence.get("native_launch_bound_seconds")
    if not isinstance(bound_seconds, int) or isinstance(bound_seconds, bool):
        return None
    if bound_seconds <= 0:
        return None
    try:
        started = parse_time(str(started_at))
        deadline = parse_time(str(deadline_at))
    except (TypeError, ValueError):
        return None
    window_end = min(started + timedelta(seconds=bound_seconds), deadline)
    return (
        started.strftime("%Y-%m-%dT%H:%M:%SZ"),
        window_end.strftime("%Y-%m-%dT%H:%M:%SZ"),
    )


def _latest_attempt(
    conn: Any,
    launch_id: str,
    lease_id: str | None = None,
) -> Any:
    p = marker(conn)
    lease_clause = f" AND lease_id={p}" if lease_id is not None else ""
    params = (launch_id, lease_id) if lease_id is not None else (launch_id,)
    return conn.execute(
        "SELECT started_at,completed_at,evidence FROM session_launch_attempts "
        f"WHERE launch_id={p}{lease_clause} "
        "ORDER BY attempt_number DESC LIMIT 1",
        params,
    ).fetchone()


def _registration_candidates(
    conn: Any,
    *,
    launch_id: str,
    project_id: int,
    surface: str,
    machine_id: str,
    workspace: str,
    native_session_id: str | None,
    window: tuple[str, str],
) -> list[str]:
    p = marker(conn)
    native_clause = f" AND s.session_id={p}" if native_session_id else ""
    lock = (
        " FOR UPDATE OF s SKIP LOCKED"
        if db_backend.connection_is_postgres(conn)
        else ""
    )
    params: list[Any] = [
        project_id,
        surface,
        machine_id,
        workspace,
        window[0],
        window[1],
    ]
    if native_session_id:
        params.append(native_session_id)
    params.append(launch_id)
    rows = conn.execute(
        "SELECT s.session_id FROM harness_sessions s "
        f"WHERE s.project_id={p} AND s.executor_surface={p} "
        f"AND s.machine_id={p} AND s.workspace={p} "
        "AND s.ended_at IS NULL AND s.terminated_at IS NULL "
        f"AND COALESCE(s.episode_started_at,s.offered_at)>={p} "
        f"AND COALESCE(s.episode_started_at,s.offered_at)<{p}"
        + native_clause
        + " AND NOT EXISTS (SELECT 1 FROM session_launches other "
        + f"WHERE other.launch_id<>{p} AND ("
        + "other.native_session_id=s.session_id OR "
        + "other.registered_session_id=s.session_id)) "
        + "ORDER BY COALESCE(s.episode_started_at,s.offered_at),s.session_id"
        + lock,
        tuple(params),
    ).fetchall()
    return [str(value(row, "session_id", 0)) for row in rows]


def reserve_launch_registration_candidate(
    conn: Any,
    *,
    launch_id: str,
    lease_id: str,
    now: str,
) -> dict[str, Any]:
    """Atomically reserve the only registration matching a supervised launch."""
    begin_mutation(conn)
    launch = get_launch(conn, launch_id, for_update=True)
    if launch.registered_session_id:
        return {
            "status": "registration_bound",
            "session_id": str(launch.registered_session_id),
        }
    if launch.state not in REGISTRATION_CANDIDATE_STATES:
        return {"status": "launch_not_waiting"}
    attempt = _latest_attempt(conn, launch_id, lease_id)
    if attempt is None or value(attempt, "completed_at", 1):
        return {"status": "launch_attempt_settled"}
    evidence = registration_evidence_document(value(attempt, "evidence", 2))
    workspace = str(evidence.get(NATIVE_LAUNCH_WORKSPACE_FIELD) or "").strip()
    window = registration_binding_window(
        value(attempt, "started_at", 0), launch.deadline_at, evidence
    )
    if not workspace:
        return {"status": SPAWN_WORKSPACE_MISSING_CODE}
    if window is None:
        return {"status": "registration_window_missing"}
    if parse_time(now) >= parse_time(window[1]):
        return {"status": "registration_window_closed"}
    candidates = _registration_candidates(
        conn,
        launch_id=launch_id,
        project_id=launch.project_id,
        surface=launch.selected_surface,
        machine_id=str(launch.assigned_machine_id or ""),
        workspace=workspace,
        native_session_id=(
            str(launch.native_session_id) if launch.native_session_id else None
        ),
        window=window,
    )
    if len(candidates) > 1:
        return {"status": "registration_ambiguous", "candidate_count": len(candidates)}
    if not candidates:
        return {"status": "registration_pending"}
    session_id = candidates[0]
    result_evidence = merge_redacted_evidence(
        launch.result_evidence,
        {
            "result_code": REGISTERED_BUT_UNBOUND_CODE,
            "registration_session_id": session_id,
            NATIVE_LAUNCH_WORKSPACE_FIELD: workspace,
        },
    )
    p = marker(conn)
    updated = conn.execute(
        "UPDATE session_launches SET native_session_id="
        + p
        + f",result_code='{REGISTERED_BUT_UNBOUND_CODE}',result_evidence="
        + p
        + f" WHERE launch_id={p} AND registered_session_id IS NULL "
        + f"AND state IN ({','.join(p for _ in sorted(REGISTRATION_CANDIDATE_STATES))}) "
        + f"AND (native_session_id IS NULL OR native_session_id={p})",
        (
            session_id,
            result_evidence,
            launch_id,
            *sorted(REGISTRATION_CANDIDATE_STATES),
            session_id,
        ),
    )
    if updated.rowcount != 1:
        return {"status": "registration_raced"}
    return {
        "status": REGISTERED_BUT_UNBOUND_CODE,
        "session_id": session_id,
        "binding_window_ends_at": window[1],
    }


def registered_candidate_for_reconcile(conn: Any, launch: Any) -> str | None:
    """Return the sole session that registered inside this launch's window.

    Reconciliation runs after the binding window has closed, so unlike the live
    reserve path it does not gate on the current time: a session that
    registered inside the window but was never bound — the relay's pid-based
    identity listing could not see a session served by a ``claude bg-spare``
    child, and often burned the whole window before the registry was consulted
    — is still the launch's rightful native session, and is adopted here rather
    than spawned over by a retry. Returns ``None`` unless exactly one candidate
    matches, so an ambiguous or empty result never guesses.
    """
    if launch.registered_session_id or launch.native_session_id:
        return None
    p = marker(conn)
    attempt = conn.execute(
        "SELECT started_at,evidence FROM session_launch_attempts "
        f"WHERE launch_id={p} ORDER BY attempt_number DESC LIMIT 1",
        (launch.launch_id,),
    ).fetchone()
    if attempt is None:
        return None
    evidence = registration_evidence_document(value(attempt, "evidence", 1))
    workspace = str(evidence.get(NATIVE_LAUNCH_WORKSPACE_FIELD) or "").strip()
    window = registration_binding_window(
        value(attempt, "started_at", 0), launch.deadline_at, evidence
    )
    if not workspace or window is None:
        return None
    candidates = _registration_candidates(
        conn,
        launch_id=launch.launch_id,
        project_id=launch.project_id,
        surface=launch.selected_surface,
        machine_id=str(launch.assigned_machine_id or ""),
        workspace=workspace,
        native_session_id=None,
        window=window,
    )
    return candidates[0] if len(candidates) == 1 else None


def wait_for_launch_registration_candidate(
    conn: Any,
    *,
    launch_id: str,
    lease_id: str,
    initial_now: str,
    wait_seconds: float = REGISTRATION_CANDIDATE_WAIT_SECONDS,
    clock: Callable[[], float] = time.monotonic,
    sleeper: Callable[[float], None] = time.sleep,
    now_provider: Callable[[], str] = utc_now,
) -> dict[str, Any]:
    """Wait briefly for hook registration, committing between observations."""
    stop_at = clock() + max(0.0, float(wait_seconds))
    current = initial_now
    while True:
        try:
            result = reserve_launch_registration_candidate(
                conn,
                launch_id=launch_id,
                lease_id=lease_id,
                now=current,
            )
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        if result["status"] not in {
            "registration_pending",
            "registration_ambiguous",
            "registration_raced",
        }:
            return result
        remaining = stop_at - clock()
        if remaining <= 0:
            return result
        sleeper(min(_REGISTRATION_POLL_SECONDS, remaining))
        current = now_provider()


__all__ = [
    "REGISTRATION_CANDIDATE_STATES",
    "registered_candidate_for_reconcile",
    "registration_binding_window",
    "registration_evidence_document",
    "reserve_launch_registration_candidate",
    "wait_for_launch_registration_candidate",
]
