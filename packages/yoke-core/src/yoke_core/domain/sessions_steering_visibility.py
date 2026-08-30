"""Read-time steering scope for the fleet session roster.

The seat's own scope is the only steering fact the roster still projects.
Launch-parent and coverage used to fill other cards from a staffing origin
that is no longer written; those fields are gone rather than left as a dead
branch over a historical enum value.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Iterable, Mapping

from yoke_core.domain import db_backend
from yoke_core.domain.schema_common import _table_exists
from yoke_core.domain.session_message_routing import session_liveness
from yoke_core.domain.sessions_holdings_claim_facts import steered_document_slugs
from yoke_core.domain.work_claim_targets import scope_int_sql


_OUTPUT_FIELDS = ("steering_scope",)


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
    documents = steered_document_slugs(
        conn, (int(scope["claim_id"]) for scope in scopes.values())
    )
    for scope in scopes.values():
        scope["strategy_docs"].extend(documents.get(int(scope["claim_id"]), []))


def steering_visibility(
    conn: Any,
    rows: list[dict[str, Any]],
    *,
    now: datetime | None = None,
) -> dict[str, dict[str, Any]]:
    """Project the holding session's steering scope and nothing else."""
    session_ids = _session_ids(rows)
    current = now or datetime.now(timezone.utc)
    scopes = _scope_rows(conn, _project_ids(rows), now=current)
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
    return projected


__all__ = ["steering_visibility"]
