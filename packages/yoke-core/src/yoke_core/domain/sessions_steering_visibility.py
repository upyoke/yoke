"""Read-time steering facts for the fleet session roster.

The seat's own scope still projects on the holding session. Worker
association is a separate live coverage fact: which steering session
covers the item the worker currently holds. Launch provenance is not
consulted, so relinking and seat handoffs move the association on the next
read.

A covered worker also carries the covering seat's own scope, because a
worker's card has to name what it is steered from — the project and the
documents — and that is the seat's fact rather than something a reader
should reconstruct by finding the seat's row elsewhere on the page.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Iterable, Mapping

from yoke_core.domain import db_backend
from yoke_core.domain.schema_common import _column_exists, _table_exists
from yoke_core.domain.session_message_routing import session_liveness
from yoke_core.domain.sessions_holdings_claim_facts import steered_document_slugs
from yoke_core.domain.steering_scope_coverage import covering_seat, live_steering_claims
from yoke_core.domain.steering_scope_membership import (
    item_coverage_target,
    item_document_links,
)
from yoke_core.domain.work_claim_targets import scope_int_sql


_OUTPUT_FIELDS = (
    "steering_scope",
    "steering_group_session_id",
    "steering_group_scope",
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


def _claim_scope(seat: Mapping[str, Any]) -> dict[str, Any] | None:
    """The covering claim's own scope, or None when it is not a real seat.

    Missing, empty, or project-less JSON must not become ``{}``. An empty
    object has no document key, and the worker row would read that as
    project-wide.
    """
    raw = seat.get("scope")
    if not isinstance(raw, Mapping):
        return None
    claim_scope = dict(raw)
    if claim_scope.get("project_id") is None:
        return None
    return claim_scope


def _covering_group_scope(
    seat: Mapping[str, Any],
    scopes: Mapping[int, Mapping[str, Any]],
) -> dict[str, Any]:
    """Name the covering claim, not every document lock on that project.

    Live seats are often two document claims on one session. Folding every
    overlapping lock onto the first claim makes a covered worker look
    project-wide. The worker row has to follow ``work_claims.scope``.
    """
    claim_scope = _claim_scope(seat)
    project_id = None if claim_scope is None else claim_scope.get("project_id")
    collapsed: Mapping[str, Any] = {}
    if project_id is not None:
        collapsed = scopes.get(int(project_id)) or {}
    document = None if claim_scope is None else claim_scope.get("document")
    group = {
        "claim_id": int(seat["claim_id"]),
        "project_id": int(project_id) if project_id is not None else None,
        "project": collapsed.get("project"),
        "holder_session_id": str(seat["session_id"]),
        "claimed_at": seat.get("claimed_at"),
        "liveness": collapsed.get("liveness"),
        "strategy_docs": [str(document)] if document else [],
    }
    if claim_scope is not None:
        group["scope"] = claim_scope
    return group


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


def _held_item_ids(
    conn: Any, session_ids: tuple[str, ...]
) -> dict[str, tuple[int, int]]:
    if not session_ids or not _table_exists(conn, "harness_sessions"):
        return {}
    if not _table_exists(conn, "items"):
        return {}
    if not _column_exists(conn, "harness_sessions", "current_item_id"):
        return {}
    marker = _marker(conn)
    rows = conn.execute(
        "SELECT s.session_id AS session_id, s.current_item_id AS item_id, "
        "i.project_id AS project_id FROM harness_sessions s "
        "JOIN items i ON CAST(i.id AS TEXT) = CAST(s.current_item_id AS TEXT) "
        "WHERE s.session_id IN ("
        + ",".join(marker for _ in session_ids)
        + ") AND s.current_item_id IS NOT NULL",
        session_ids,
    ).fetchall()
    held: dict[str, tuple[int, int]] = {}
    for row in rows:
        record = dict(row)
        if record.get("item_id") is None or record.get("project_id") is None:
            continue
        held[str(record["session_id"])] = (
            int(record["item_id"]),
            int(record["project_id"]),
        )
    return held


def steering_visibility(
    conn: Any,
    rows: list[dict[str, Any]],
    *,
    now: datetime | None = None,
) -> dict[str, dict[str, Any]]:
    """Project the seat's scope and the live coverage association."""
    session_ids = _session_ids(rows)
    current = now or datetime.now(timezone.utc)
    scopes = _scope_rows(conn, _project_ids(rows), now=current)
    claims = (
        live_steering_claims(conn)
        if _table_exists(conn, "work_claims")
        else []
    )
    holders = {str(claim["session_id"]) for claim in claims}
    held_items = _held_item_ids(conn, session_ids)
    # Every covered worker's target names the document its held item is
    # linked to. Asking per row made the read one link query per session; the
    # page's items are known here, so the whole set resolves in one.
    document_links = item_document_links(
        conn, (item_id for item_id, _project_id in held_items.values()),
    )
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
        if session_id in holders:
            projected[session_id]["steering_group_session_id"] = session_id
            continue
        item = held_items.get(session_id)
        if item is None:
            continue
        item_id, item_project_id = item
        seat = covering_seat(
            conn,
            item_coverage_target(
                conn,
                project_id=item_project_id,
                item_id=item_id,
                links=document_links,
            ),
            claims=claims,
        )
        if seat is not None:
            projected[session_id]["steering_group_session_id"] = str(
                seat["session_id"]
            )
            projected[session_id]["steering_group_scope"] = (
                _covering_group_scope(seat, scopes)
            )
    return projected


__all__ = ["steering_visibility"]
