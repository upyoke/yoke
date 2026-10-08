"""Authorized, indexed time-range reads over disposable timing events."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from yoke_core.domain.actor_permissions import PERM_EVENTS_READ, PermissionDenied
from yoke_core.domain.actor_project_visibility import (
    actor_project_ids_with_permission,
    numeric_actor_id,
)
from yoke_core.domain.performance_observations import TIMING_EVENTS, unique_observations

MAX_OBSERVATIONS = 250_000


def authorized_predicate(
    conn: Any, actor_id: Any, projects: list[int] | None
) -> tuple[str, list[Any]]:
    """Authorize before reading events or command summaries; never infer project attribution."""
    actor = numeric_actor_id(actor_id)
    visible = actor_project_ids_with_permission(conn, actor, PERM_EVENTS_READ)
    if projects is not None:
        requested = set(projects)
        if visible is not None and not requested.issubset(visible):
            raise PermissionDenied(
                "performance_scope_denied: select projects where you hold events.read"
            )
        selected = sorted(requested)
    elif visible is None:
        return "TRUE", []
    else:
        selected = sorted(visible)
    predicate = (
        "e.project_id IN (" + ",".join("%s" for _ in selected) + ")"
        if selected
        else "FALSE"
    )
    params: list[Any] = list(selected)
    # Universe-attributed rows are never assigned to a project. They require
    # an actual org-admin grant, not an owner grant on one visible project.
    if projects is None and actor is not None:
        rows = conn.execute(
            "SELECT a.org_id FROM actor_org_roles a JOIN roles r ON r.id=a.role_id "
            "WHERE a.actor_id=%s AND r.name='admin'",
            (actor,),
        ).fetchall()
        orgs = [str(row[0]) for row in rows]
        if orgs:
            predicate = (
                f"({predicate} OR (e.project_id IS NULL AND e.org_id IN ("
                + ",".join("%s" for _ in orgs)
                + ")))"
            )
            params.extend(orgs)
    return predicate, params


def read_observations(
    conn: Any, actor_id: Any, projects: list[int] | None, start: datetime, end: datetime
) -> list[dict[str, Any]]:
    predicate, params = authorized_predicate(conn, actor_id, projects)
    names = ",".join("%s" for _ in TIMING_EVENTS)
    # The source's indexed created_at, event_name and project_id predicates
    # restrict this read. No tool responses or ledger results are loaded.
    rows = conn.execute(
        "SELECT e.event_id, e.event_name, e.created_at, e.duration_ms, "
        "json_build_object('context', json_build_object("
        "'function', COALESCE(e.envelope::jsonb->'context'->'detail'->'function', e.envelope::jsonb->'context'->'function'), "
        "'executor', COALESCE(e.envelope::jsonb->'context'->'detail'->'executor', e.envelope::jsonb->'context'->'executor'), "
        "'client_wall_ms', COALESCE(e.envelope::jsonb->'context'->'detail'->'client_wall_ms', e.envelope::jsonb->'context'->'client_wall_ms'))) AS envelope, "
        "e.session_id, e.tool_use_id, e.tool_name, e.hook_event_name, e.event_outcome, "
        "e.trace_id, e.project_id, hs.executor, hs.executor_surface, hs.machine_id, "
        "stc.started_at, stc.completed_at, stc.command_summary "
        "FROM events e LEFT JOIN harness_sessions hs ON hs.session_id=e.session_id "
        "LEFT JOIN session_tool_calls stc ON stc.session_id=e.session_id "
        "AND stc.tool_use_id=e.tool_use_id "
        f"WHERE ({predicate}) AND e.created_at >= %s AND e.created_at < %s "
        f"AND e.event_name IN ({names}) ORDER BY e.created_at, e.id LIMIT %s",
        (
            *params,
            start.isoformat().replace("+00:00", "Z"),
            end.isoformat().replace("+00:00", "Z"),
            *TIMING_EVENTS,
            MAX_OBSERVATIONS + 1,
        ),
    ).fetchall()
    if len(rows) > MAX_OBSERVATIONS:
        raise ValueError(
            f"performance_observation_budget: range exceeds {MAX_OBSERVATIONS} observations; "
            "shorten the time range. No partial aggregate was returned."
        )
    return unique_observations([dict(row) for row in rows], datetime.now(timezone.utc))


def details(
    observations: list[dict[str, Any]], family: str | None, offset: int, limit: int
) -> dict[str, Any]:
    selected = [v for v in observations if family is None or v["family"] == family]
    selected.sort(
        key=lambda v: (
            v["duration_ms"] is not None,
            v["duration_ms"] or 0,
            v["event_id"],
        ),
        reverse=True,
    )
    rows = selected[offset : offset + limit]
    return {
        "rows": rows,
        "total": len(selected),
        "offset": offset,
        "next_offset": offset + limit if offset + limit < len(selected) else None,
        "sampling": "none; all matching observations ranked by raw duration",
        "span_coverage": "Recorded event/owner timings only. OTel request/DB/external spans are not stored in the event ledger; absent spans are unknown, not zero. Nested client/evaluator timings must not be summed.",
    }
