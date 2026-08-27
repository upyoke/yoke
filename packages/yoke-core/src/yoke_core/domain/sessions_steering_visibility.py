"""Read-time steering scope, launch provenance, and report custody facts."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Iterable, Mapping

from yoke_contracts.session_control.launch_origin import (
    LAUNCH_ORIGIN_STEERING_BACKSTOP,
)
from yoke_contracts.turn_end_evidence import STEERING_REPORT_IDEMPOTENCY_PREFIX
from yoke_core.domain import db_backend
from yoke_core.domain.schema_common import _table_exists
from yoke_core.domain.session_message_routing import session_liveness
from yoke_core.domain.work_claim_targets import scope_int_sql


_OUTPUT_FIELDS = (
    "steering_scope",
    "steering_parent",
    "steering_coverage",
    "steering_report",
)


def _marker(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def _session_ids(rows: Iterable[Mapping[str, Any]]) -> tuple[str, ...]:
    return tuple(
        dict.fromkeys(
            str(row.get("session_id") or "") for row in rows if row.get("session_id")
        )
    )


def _project_ids(rows: Iterable[Mapping[str, Any]]) -> tuple[int, ...]:
    return tuple(
        dict.fromkeys(
            int(row["project_id"]) for row in rows if row.get("project_id") is not None
        )
    )


def _scope_rows(
    conn: Any,
    project_ids: tuple[int, ...],
    *,
    now: datetime,
) -> dict[int, dict[str, Any]]:
    required = ("projects", "harness_sessions", "work_claims")
    if not project_ids or not all(_table_exists(conn, name) for name in required):
        return {}
    marker = _marker(conn)
    project_id = scope_int_sql(conn, "claim.scope", "project_id")
    rows = conn.execute(
        "SELECT claim.id AS claim_id,claim.session_id,claim.claimed_at,"
        "project.id AS project_id,project.slug AS project,"
        "holder.last_heartbeat,holder.last_tool_call_at,holder.ended_at,"
        "holder.terminated_at,holder.executor "
        "FROM work_claims claim "
        f"JOIN projects project ON project.id={project_id} "
        "JOIN harness_sessions holder ON holder.session_id=claim.session_id "
        "WHERE claim.target_kind='steering' AND claim.released_at IS NULL "
        "AND project.id IN ("
        + ",".join(marker for _ in project_ids)
        + ") ORDER BY claim.claimed_at,claim.id",
        project_ids,
    ).fetchall()
    scopes: dict[int, dict[str, Any]] = {}
    for row in rows:
        row_dict = dict(row)
        scope = {
            "claim_id": int(row_dict["claim_id"]),
            "project_id": int(row_dict["project_id"]),
            "project": row_dict["project"],
            "holder_session_id": str(row_dict["session_id"]),
            "claimed_at": row_dict["claimed_at"],
            "liveness": session_liveness(row_dict, now=now),
            "strategy_docs": [],
        }
        scopes.setdefault(scope["project_id"], scope)
    _attach_strategy_docs(conn, scopes)
    return scopes


def _attach_strategy_docs(
    conn: Any,
    scopes: dict[int, dict[str, Any]],
) -> None:
    if not scopes or not _table_exists(conn, "strategy_doc_claims"):
        return
    marker = _marker(conn)
    holders = tuple(scope["holder_session_id"] for scope in scopes.values())
    projects = tuple(scopes)
    rows = conn.execute(
        "SELECT project_id,owner_session_id,strategy_doc_slug "
        "FROM strategy_doc_claims WHERE owner_kind='session' "
        "AND released_at IS NULL AND project_id IN ("
        + ",".join(marker for _ in projects)
        + ") AND owner_session_id IN ("
        + ",".join(marker for _ in holders)
        + ") ORDER BY project_id,strategy_doc_slug",
        (*projects, *holders),
    ).fetchall()
    for row in rows:
        scope = scopes.get(int(row["project_id"]))
        if scope and scope["holder_session_id"] == str(row["owner_session_id"]):
            scope["strategy_docs"].append(str(row["strategy_doc_slug"]))


def _launches(
    conn: Any,
    session_ids: tuple[str, ...],
) -> tuple[set[str], dict[str, dict[str, Any]]]:
    required = ("session_launch_attempts", "session_launches", "projects")
    if not session_ids or not all(_table_exists(conn, name) for name in required):
        return set(), {}
    marker = _marker(conn)
    rows = conn.execute(
        "SELECT attempt.native_session_id,launch.launch_id,"
        "launch.requester_session_id,launch.project_id,project.slug AS project,"
        "launch.origin,attempt.started_at,attempt.attempt_number "
        "FROM session_launch_attempts attempt "
        "JOIN session_launches launch ON launch.launch_id=attempt.launch_id "
        "JOIN projects project ON project.id=launch.project_id "
        "WHERE attempt.native_session_id IN ("
        + ",".join(marker for _ in session_ids)
        + ") ORDER BY attempt.started_at DESC,attempt.attempt_number DESC",
        session_ids,
    ).fetchall()
    launched: set[str] = set()
    steering: dict[str, dict[str, Any]] = {}
    for row in rows:
        session_id = str(row["native_session_id"])
        if session_id in launched:
            continue
        launched.add(session_id)
        if row["origin"] == LAUNCH_ORIGIN_STEERING_BACKSTOP:
            steering[session_id] = {
                "session_id": str(row["requester_session_id"] or ""),
                "project_id": int(row["project_id"]),
                "project": row["project"],
                "launch_id": row["launch_id"],
            }
    return launched, steering


def _latest_reports(
    conn: Any,
    session_ids: tuple[str, ...],
) -> dict[str, dict[str, Any]]:
    required = (
        "session_messages",
        "session_message_recipients",
    )
    if not session_ids or not all(_table_exists(conn, name) for name in required):
        return {}
    marker = _marker(conn)
    rows = conn.execute(
        "SELECT message.sender_session_id,message.message_id,"
        "recipient.session_id AS recipient_session_id,recipient.state,"
        "message.created_at,recipient.acknowledged_at "
        "FROM session_messages message JOIN session_message_recipients recipient "
        "ON recipient.message_id=message.message_id "
        "WHERE message.sender_session_id IN ("
        + ",".join(marker for _ in session_ids)
        + f") AND message.idempotency_key LIKE {marker} "
        "ORDER BY message.created_at DESC,message.message_id DESC",
        (*session_ids, f"{STEERING_REPORT_IDEMPOTENCY_PREFIX}%"),
    ).fetchall()
    reports: dict[str, dict[str, Any]] = {}
    for row in rows:
        session_id = str(row["sender_session_id"])
        reports.setdefault(
            session_id,
            {
                "message_id": row["message_id"],
                "recipient_session_id": str(row["recipient_session_id"]),
                "recipient_state": row["state"],
                "created_at": row["created_at"],
                "acknowledged_at": row["acknowledged_at"],
            },
        )
    return reports


def steering_visibility(
    conn: Any,
    rows: list[dict[str, Any]],
    *,
    now: datetime | None = None,
) -> dict[str, dict[str, Any]]:
    """Project steering facts without introducing a second state store."""
    session_ids = _session_ids(rows)
    current = now or datetime.now(timezone.utc)
    scopes = _scope_rows(conn, _project_ids(rows), now=current)
    launched, steering_launches = _launches(conn, session_ids)
    reports = _latest_reports(conn, session_ids)
    projected = {
        session_id: {field: None for field in _OUTPUT_FIELDS}
        for session_id in session_ids
    }
    for row in rows:
        session_id = str(row.get("session_id") or "")
        project_id = row.get("project_id")
        scope = scopes.get(int(project_id)) if project_id is not None else None
        if scope and scope["holder_session_id"] == session_id:
            projected[session_id]["steering_scope"] = scope
        elif scope and session_id not in launched:
            projected[session_id]["steering_coverage"] = scope
        projected[session_id]["steering_parent"] = steering_launches.get(session_id)
        projected[session_id]["steering_report"] = reports.get(session_id)
    return projected


__all__ = ["steering_visibility"]
