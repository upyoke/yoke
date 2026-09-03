"""Keep a registering launch session alive until delivery can bind."""

from __future__ import annotations

from typing import Any, Mapping, Sequence

from yoke_contracts.session_control.launch_registration import (
    LAUNCH_DELIVERY_PENDING_STATUS,
    NATIVE_LAUNCH_WORKSPACE_FIELD,
)
from yoke_core.domain.schema_common import _column_exists, _table_exists
from yoke_core.domain.session_launch_registration_candidate import (
    REGISTRATION_CANDIDATE_STATES,
    registration_binding_window,
    registration_evidence_document,
)
from yoke_core.domain.session_launch_store import marker, parse_time, utc_now
from yoke_core.domain.session_message_types import row_dict


def _schema_available(conn: Any) -> bool:
    required = {
        "session_launches": {
            "launch_id",
            "state",
            "project_id",
            "selected_surface",
            "assigned_machine_id",
            "native_session_id",
            "registered_session_id",
            "deadline_at",
        },
        "session_launch_attempts": {
            "launch_id",
            "attempt_number",
            "started_at",
            "evidence",
        },
        "harness_sessions": {
            "session_id",
            "project_id",
            "executor_surface",
            "machine_id",
            "workspace",
            "offered_at",
            "ended_at",
        },
    }
    return all(
        _table_exists(conn, table)
        and all(_column_exists(conn, table, column) for column in columns)
        for table, columns in required.items()
    )


def _sessions(conn: Any, targets: tuple[str, ...]) -> dict[str, dict[str, Any]]:
    p = marker(conn)
    has_episode = _column_exists(conn, "harness_sessions", "episode_started_at")
    has_terminated = _column_exists(conn, "harness_sessions", "terminated_at")
    registered_at = (
        "COALESCE(episode_started_at,offered_at)" if has_episode else "offered_at"
    )
    terminal_clause = " AND terminated_at IS NULL" if has_terminated else ""
    rows = conn.execute(
        "SELECT session_id,project_id,executor_surface,machine_id,workspace,"
        + registered_at
        + " AS registered_at FROM harness_sessions WHERE session_id IN ("
        + ",".join(p for _ in targets)
        + ") AND ended_at IS NULL"
        + terminal_clause,
        targets,
    ).fetchall()
    return {str(row_dict(row)["session_id"]): row_dict(row) for row in rows}


def _launches(conn: Any) -> list[Any]:
    p = marker(conn)
    states = sorted(REGISTRATION_CANDIDATE_STATES)
    return conn.execute(
        "SELECT l.launch_id,l.state,l.project_id,l.selected_surface,"
        "l.assigned_machine_id,l.native_session_id,l.registered_session_id,"
        "l.deadline_at,a.started_at,a.evidence FROM session_launches l "
        "JOIN session_launch_attempts a ON a.attempt_id=("
        "SELECT latest.attempt_id FROM session_launch_attempts latest "
        "WHERE latest.launch_id=l.launch_id "
        "ORDER BY latest.attempt_number DESC LIMIT 1) "
        f"WHERE l.state IN ({','.join(p for _ in states)}) "
        "AND l.registered_session_id IS NULL",
        tuple(states),
    ).fetchall()


def _bindings(conn: Any) -> list[Any]:
    return conn.execute(
        "SELECT launch_id,native_session_id,registered_session_id "
        "FROM session_launches WHERE native_session_id IS NOT NULL "
        "OR registered_session_id IS NOT NULL"
    ).fetchall()


def pending_launch_deliveries(
    conn: Any,
    session_ids: Sequence[str],
    *,
    now: str | None = None,
) -> dict[str, dict[str, Any]]:
    """Return launch-window holds for newly registered, still-unbound sessions."""
    targets = tuple(dict.fromkeys(str(one) for one in session_ids if str(one)))
    if not targets or not _schema_available(conn):
        return {}
    sessions = _sessions(conn, targets)
    if not sessions:
        return {}
    all_bindings = _bindings(conn)
    current = parse_time(now or utc_now())
    matches: dict[str, list[tuple[str, str]]] = {}
    for raw in _launches(conn):
        launch = row_dict(raw)
        evidence = registration_evidence_document(launch.get("evidence"))
        workspace = str(evidence.get(NATIVE_LAUNCH_WORKSPACE_FIELD) or "")
        window = registration_binding_window(
            launch.get("started_at"), launch.get("deadline_at"), evidence
        )
        if not workspace or window is None or current >= parse_time(window[1]):
            continue
        for session_id, session in sessions.items():
            if not _session_matches_launch(session, launch, workspace, window):
                continue
            if _bound_to_other_launch(
                all_bindings, session_id, str(launch["launch_id"])
            ):
                continue
            matches.setdefault(session_id, []).append(
                (str(launch["launch_id"]), window[1])
            )
    return {
        session_id: _pending_delivery_facts(rows)
        for session_id, rows in matches.items()
    }


def _session_matches_launch(
    session: Mapping[str, Any],
    launch: Mapping[str, Any],
    workspace: str,
    window: tuple[str, str],
) -> bool:
    native = str(launch.get("native_session_id") or "")
    registered_at = str(session.get("registered_at") or "")
    return bool(
        (not native or native == str(session.get("session_id") or ""))
        and int(session.get("project_id") or 0) == int(launch.get("project_id") or -1)
        and str(session.get("executor_surface") or "")
        == str(launch.get("selected_surface") or "")
        and str(session.get("machine_id") or "")
        == str(launch.get("assigned_machine_id") or "")
        and str(session.get("workspace") or "") == workspace
        and registered_at >= window[0]
        and registered_at < window[1]
    )


def _bound_to_other_launch(
    rows: Sequence[Any], session_id: str, launch_id: str
) -> bool:
    for raw in rows:
        row = row_dict(raw)
        if str(row["launch_id"]) == launch_id:
            continue
        if session_id in {
            str(row.get("native_session_id") or ""),
            str(row.get("registered_session_id") or ""),
        }:
            return True
    return False


def _pending_delivery_facts(rows: Sequence[tuple[str, str]]) -> dict[str, Any]:
    ordered = sorted(set(rows))
    launch_ids = [launch_id for launch_id, _window_end in ordered]
    facts: dict[str, Any] = {
        "status": LAUNCH_DELIVERY_PENDING_STATUS,
        "active_claim_count": 0,
        "launch_count": len(launch_ids),
        "launch_ids": launch_ids,
        "binding_window_ends_at": min(end for _launch_id, end in ordered),
    }
    if len(launch_ids) == 1:
        facts["launch_id"] = launch_ids[0]
        facts["recovery"] = f"yoke session-control launch get {launch_ids[0]} --json"
    return facts


__all__ = ["pending_launch_deliveries"]
