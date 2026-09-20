"""Compose decision-request rows for a whole page, one read per question.

A gate row is assembled from four tables — the request itself, the roles it
addresses, the people it names, and the answers it has collected. Composing
one row at a time asked each of those questions once per gate on the page,
so an Inbox showing ten gates paid forty round trips for four answers. Every
question here is asked once for the set; :func:`request_row` is the
one-element case the write paths still use.
"""

from __future__ import annotations

import json
from typing import Any, Iterable

from yoke_core.domain import db_backend
from yoke_core.domain.approval_policy import DEFAULT_APPROVAL_MODE
from yoke_core.domain.decision_request_contract import DECISION_KINDS
from yoke_core.domain.decision_answers import decisions_for_requests
from yoke_core.domain.decision_request_live_evidence import live_evidence


def _p(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def _grouped(conn: Any, sql: str, ids: tuple[int, ...]) -> dict[int, list[Any]]:
    rows = conn.execute(
        sql.format(placeholders=", ".join(_p(conn) for _ in ids)), ids
    ).fetchall()
    grouped: dict[int, list[Any]] = {}
    for row in rows:
        grouped.setdefault(int(row[0]), []).append(row)
    return grouped


def request_rows(conn: Any, request_ids: Iterable[int]) -> dict[int, dict[str, Any]]:
    """Compose each named request, keyed by id; unknown ids are absent.

    Live evidence stays per request because it is a question about that
    request's own subject rather than one the page shares.
    """
    ids = tuple(dict.fromkeys(int(value) for value in request_ids))
    if not ids:
        return {}
    from yoke_core.domain.approval_decisions import evaluate_decisions

    placeholders = ", ".join(_p(conn) for _ in ids)
    rows = conn.execute(
        f"SELECT * FROM decision_requests WHERE id IN ({placeholders})",
        ids,
    ).fetchall()
    roles = _grouped(
        conn,
        "SELECT request_id, scope_kind, scope_id, role_name "
        "FROM decision_request_role_authorities "
        "WHERE request_id IN ({placeholders}) "
        "ORDER BY request_id, role_name, scope_id",
        ids,
    )
    named = _grouped(
        conn,
        "SELECT request_id, actor_id FROM decision_request_actor_authorities "
        "WHERE request_id IN ({placeholders}) ORDER BY request_id, actor_id",
        ids,
    )
    answers = decisions_for_requests(conn, ids)
    composed: dict[int, dict[str, Any]] = {}
    for raw in rows:
        result = dict(raw)
        request_id = int(result["id"])
        try:
            result["subject_context"] = json.loads(result["subject_context"] or "{}")
        except (TypeError, json.JSONDecodeError):
            result["subject_context"] = {}
        if result["status"] == "pending":
            live = live_evidence(
                conn,
                result["kind"],
                result["subject_context"],
                subject_key=result["subject_key"],
                project_id=result.get("project_id"),
            )
            if live is not None:
                result["subject_context"].update(live)
        result["actions"] = list(DECISION_KINDS[result["kind"]].actions)
        result["role_authorities"] = [
            {
                "scope_kind": row[1],
                "scope_id": row[2],
                "role_name": row[3],
            }
            for row in roles.get(request_id, [])
        ]
        result["named_actor_ids"] = [
            int(row[1]) for row in named.get(request_id, [])
        ]
        result["approval_mode"] = str(
            result.get("approval_mode") or DEFAULT_APPROVAL_MODE
        )
        result["decisions"] = answers.get(request_id, [])
        result["approval_progress"] = evaluate_decisions(
            conn, result, decisions=result["decisions"],
        ).as_dict()
        composed[request_id] = result
    return composed


def request_row(conn: Any, request_id: int) -> dict[str, Any]:
    """Compose one request, the one-element case of :func:`request_rows`."""
    composed = request_rows(conn, (int(request_id),)).get(int(request_id))
    if composed is None:
        raise LookupError(f"decision request {request_id} does not exist")
    return composed


__all__ = ["request_row", "request_rows"]
