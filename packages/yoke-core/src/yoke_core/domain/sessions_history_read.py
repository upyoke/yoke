"""Compact, cursor-paged reads for ended session history."""

from __future__ import annotations

import base64
from typing import Any, Collection, Optional, Sequence

from yoke_contracts.session_control.liveness import (
    ENDED_CAUSE_KILLED,
    ENDED_CAUSE_WOUND_DOWN,
    ended_session_sql,
)
from yoke_core.domain.json_helper import dumps_compact, loads_text
from yoke_core.domain.project_identity import placeholder, row_value
from yoke_core.domain.session_list_fields import (
    USAGE_PROJECTION_FIELDS,
    usage_fields,
)
from yoke_core.domain.session_probe import not_probe_session_sql


DEFAULT_HISTORY_LIMIT = 50
MAX_HISTORY_LIMIT = 100
HISTORY_FIELDS = (
    "session_id", "project_id", "project", "focus", "recent_item",
    "recent_item_title", "actor_id", "actor_kind", "actor_label",
    "executor", "executor_surface", "model", "requested_model",
    "machine_id", "machine_name", "activity_at", "ended_at",
    "terminated_at", "ended_cause", "termination_reason",
    *USAGE_PROJECTION_FIELDS,
)

_ACTIVITY = (
    "GREATEST(COALESCE(s.last_tool_call_at, ''), "
    "COALESCE(s.last_heartbeat, ''), COALESCE(s.ended_at, ''), "
    "COALESCE(s.terminated_at, ''))"
)
_MACHINE_NAME = (
    "(SELECT sr.hostname FROM session_relays sr "
    "WHERE sr.machine_id = s.machine_id AND sr.hostname IS NOT NULL "
    "ORDER BY sr.last_seen_at DESC LIMIT 1)"
)


def _actor_label() -> str:
    """SQL rendering the session's actor to the name every surface shows."""
    return "COALESCE(NULLIF(a.name, ''), a.system_component, '')"


def _cursor_encode(activity_at: str, session_id: str) -> str:
    raw = dumps_compact({"activity_at": activity_at, "session_id": session_id})
    return base64.urlsafe_b64encode(raw.encode()).decode().rstrip("=")


def _cursor_decode(value: Optional[str]) -> Optional[tuple[str, str]]:
    if value is None:
        return None
    try:
        padding = "=" * (-len(value) % 4)
        decoded = base64.urlsafe_b64decode((value + padding).encode()).decode()
        payload = loads_text(decoded)
        activity = payload["activity_at"]  # type: ignore[index]
        session_id = payload["session_id"]  # type: ignore[index]
        if not isinstance(activity, str) or not activity:
            raise ValueError
        if not isinstance(session_id, str) or not session_id:
            raise ValueError
        if set(payload) != {"activity_at", "session_id"}:  # type: ignore[arg-type]
            raise ValueError
        return activity, session_id
    except (KeyError, TypeError, UnicodeError, ValueError):
        raise ValueError(
            "history.cursor is invalid; clear it and reload the first history page"
        ) from None


def _scope(
    conn: Any,
    project_ids: Optional[Collection[int]],
) -> tuple[list[str], list[Any]]:
    clauses = [ended_session_sql("s"), not_probe_session_sql("s")]
    params: list[Any] = []
    marker = placeholder(conn)
    if project_ids is not None:
        ids = sorted({int(value) for value in project_ids})
        if not ids:
            clauses.append("1 = 0")
        else:
            clauses.append(f"s.project_id IN ({', '.join(marker for _ in ids)})")
            params.extend(ids)
    return clauses, params


def _where(clauses: Sequence[str]) -> str:
    return "WHERE " + " AND ".join(clauses)


def _facet_rows(conn: Any, clauses: Sequence[str], params: Sequence[Any]) -> dict:
    where = _where(clauses)
    projects = conn.execute(
        "SELECT DISTINCT pr.id, pr.slug FROM harness_sessions s "
        "LEFT JOIN projects pr ON pr.id = s.project_id "
        f"{where} AND pr.id IS NOT NULL ORDER BY pr.slug",
        tuple(params),
    ).fetchall()
    harness_rows = conn.execute(
        "SELECT DISTINCT s.executor, s.executor_surface FROM harness_sessions s "
        f"{where}", tuple(params),
    ).fetchall()
    machines = conn.execute(
        "SELECT DISTINCT s.machine_id, " + _MACHINE_NAME + " AS machine_name "
        "FROM harness_sessions s " + where + " AND s.machine_id IS NOT NULL "
        "ORDER BY s.machine_id", tuple(params),
    ).fetchall()
    harnesses = sorted({
        str(value)
        for raw in harness_rows
        for value in (row_value(raw, "executor", 0), row_value(raw, "executor_surface", 1))
        if value
    })
    return {
        "projects": [
            {"id": int(row_value(raw, "id", 0)), "slug": str(row_value(raw, "slug", 1))}
            for raw in projects
        ],
        "harnesses": harnesses,
        "machines": [
            {
                "id": str(row_value(raw, "machine_id", 0)),
                "label": str(row_value(raw, "machine_name", 1) or row_value(raw, "machine_id", 0)),
            }
            for raw in machines
        ],
    }


def read_ended_session_history(
    conn: Any,
    *,
    project_ids: Optional[Collection[int]],
    search: str = "",
    harnesses: Sequence[str] = (),
    machines: Sequence[str] = (),
    limit: int = DEFAULT_HISTORY_LIMIT,
    cursor: Optional[str] = None,
) -> dict[str, Any]:
    """Return one compact ended-history page within resolved project ids."""
    marker = placeholder(conn)
    scope_clauses, scope_params = _scope(conn, project_ids)
    facets = _facet_rows(conn, scope_clauses, scope_params)
    clauses = list(scope_clauses)
    params = list(scope_params)
    actor_label = _actor_label()
    actor_params: list[str] = []
    normalized_search = search.strip().lower()
    if normalized_search:
        searchable = (
            "LOWER(COALESCE(s.session_id, '') || ' ' || COALESCE(pr.slug, '') || ' ' || "
            "COALESCE(fi.title, '') || ' ' || COALESCE(" + actor_label + ", '') || ' ' || "
            "COALESCE(s.model, '') || ' ' || COALESCE(s.requested_model, ''))"
        )
        clauses.append(f"{searchable} LIKE {marker}")
        params.extend([*actor_params, f"%{normalized_search}%"])
    normalized_harnesses = sorted({str(value).strip() for value in harnesses if str(value).strip()})
    if normalized_harnesses:
        clauses.append(
            "(s.executor IN (" + ", ".join(marker for _ in normalized_harnesses)
            + ") OR s.executor_surface IN ("
            + ", ".join(marker for _ in normalized_harnesses) + "))"
        )
        params.extend([*normalized_harnesses, *normalized_harnesses])
    normalized_machines = sorted({str(value).strip() for value in machines if str(value).strip()})
    if normalized_machines:
        clauses.append(
            "s.machine_id IN (" + ", ".join(marker for _ in normalized_machines) + ")"
        )
        params.extend(normalized_machines)
    match_clauses = list(clauses)
    match_params = list(params)
    decoded_cursor = _cursor_decode(cursor)
    if decoded_cursor is not None:
        activity_at, session_id = decoded_cursor
        clauses.append(f"({_ACTIVITY} < {marker} OR ({_ACTIVITY} = {marker} AND s.session_id < {marker}))")
        params.extend([activity_at, activity_at, session_id])

    joins = (
        "FROM harness_sessions s "
        "LEFT JOIN projects pr ON pr.id = s.project_id "
        "LEFT JOIN actors a ON a.id = s.actor_id "
        "LEFT JOIN items fi ON CAST(fi.id AS TEXT) = "
        "COALESCE(NULLIF(s.recent_item_id, ''), NULLIF(s.current_item_id, '')) "
        "LEFT JOIN projects fpr ON fpr.id = fi.project_id "
    )
    where = _where(clauses)
    count_row = conn.execute(
        "SELECT COUNT(*) AS matched_count " + joins + _where(match_clauses),
        tuple(match_params),
    ).fetchone()
    query_params = [*actor_params]
    query_params.extend(params)
    query_params.append(limit + 1)
    rows = conn.execute(
        "SELECT s.session_id, s.project_id, pr.slug AS project, "
        "fi.title AS recent_item_title, fi.project_sequence, "
        "fpr.public_item_prefix, s.actor_id, a.kind AS actor_kind, "
        + actor_label + " AS actor_label, s.executor, s.executor_surface, "
        "s.model, s.requested_model, s.machine_id, " + _MACHINE_NAME + " AS machine_name, "
        + _ACTIVITY + " AS activity_at, s.ended_at, s.terminated_at, "
        "s.termination_reason, s.usage_totals " + joins + where
        + f" ORDER BY {_ACTIVITY} DESC, s.session_id DESC LIMIT {marker}",
        tuple(query_params),
    ).fetchall()
    has_more = len(rows) > limit
    page = rows[:limit]
    rendered = []
    for raw in page:
        row = dict(raw)
        prefix = row.get("public_item_prefix")
        sequence = row.get("project_sequence")
        recent_item = f"{prefix}-{sequence}" if prefix and sequence is not None else None
        rendered.append({
            "session_id": str(row["session_id"]),
            "project_id": row.get("project_id"),
            "project": row.get("project"),
            "focus": row.get("recent_item_title") or row.get("project"),
            "recent_item": recent_item,
            "recent_item_title": row.get("recent_item_title"),
            "actor_id": row.get("actor_id"),
            "actor_kind": row.get("actor_kind"),
            "actor_label": row.get("actor_label"),
            "executor": row.get("executor"),
            "executor_surface": row.get("executor_surface"),
            "model": row.get("model"),
            "requested_model": row.get("requested_model"),
            "machine_id": row.get("machine_id"),
            "machine_name": row.get("machine_name"),
            "activity_at": row.get("activity_at"),
            "ended_at": row.get("ended_at"),
            "terminated_at": row.get("terminated_at"),
            "ended_cause": ENDED_CAUSE_KILLED if row.get("terminated_at") else ENDED_CAUSE_WOUND_DOWN,
            "termination_reason": row.get("termination_reason"),
            **usage_fields(row),
        })
    next_cursor = None
    if has_more and rendered:
        last = rendered[-1]
        next_cursor = _cursor_encode(str(last["activity_at"]), str(last["session_id"]))
    return {
        "fields": list(HISTORY_FIELDS),
        "rows": rendered,
        "matched_count": int(row_value(count_row, "matched_count", 0)) if count_row else 0,
        "next_cursor": next_cursor,
        "facets": facets,
    }


__all__ = [
    "DEFAULT_HISTORY_LIMIT", "HISTORY_FIELDS", "MAX_HISTORY_LIMIT",
    "read_ended_session_history",
]
