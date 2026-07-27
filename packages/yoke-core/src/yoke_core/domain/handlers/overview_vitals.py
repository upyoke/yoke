"""Authoritative state and momentum facts for the universe Overview.

These are the same signals the terminal board prints, so the two have to
agree: an operator reading `yoke board` and the same universe's Overview
must not see different numbers for the same scope. That constrains what
each measure may count — state counts expand an epic into its tasks, and
the issues meter counts work reaching a terminal success rather than work
being filed — because the board's own meters are defined that way.

Two signals match in direction but not in grain, because the board reads
them from somewhere a server cannot. Code volume is lines changed per
day from a local checkout's commit cache, counted here as the git-shaped
rows in the event stream; strategy volume is bytes authored, counted here
as revisions written. Both rise and fall with the board's, but neither is
the same magnitude, so read them as trends rather than totals.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from pydantic import BaseModel

from yoke_contracts.api.function_call import (
    FunctionCallRequest,
    FunctionError,
    HandlerOutcome,
)
from yoke_contracts.board.status import status_to_board_bucket
from yoke_core.domain.handlers.overview_strategy_timeline import (
    strategy_timelines as _strategy_timelines,
)


class OverviewVitalsRequest(BaseModel):
    project: Optional[str] = None
    days: int = 120


class OverviewVitalsResponse(BaseModel):
    state_counts: Dict[str, int]
    momentum: List[Dict[str, Any]]
    strategy_timeline: List[Dict[str, Any]]
    days: int


_STATE_GROUPS = {
    "idea": "backlog",
    "planning": "pipeline",
    "refined": "pipeline",
    "implementing": "active",
    "reviewing": "active",
    "implemented": "active",
    "release": "active",
    "blocked": "blocked",
    "frozen": "frozen",
    "done": "done",
    "unknown": "unknown",
}


def _error(message: str, jsonpath: str = "$.payload") -> HandlerOutcome:
    return HandlerOutcome(
        primary_success=False,
        error=FunctionError(
            code="payload_invalid",
            message=message,
            jsonpath=jsonpath,
        ),
    )


def _visible_project_ids(request: FunctionCallRequest, conn: Any) -> list[int]:
    raw = (request.options or {}).get("visible_project_ids")
    if raw is not None:
        values: list[int] = []
        for value in raw if isinstance(raw, list) else []:
            try:
                values.append(int(value))
            except (TypeError, ValueError):
                continue
        return sorted(set(values))
    actor_text = str(
        request.actor.actor_id if request.actor is not None else "",
    ).strip()
    if actor_text.isdigit():
        from yoke_core.domain.actor_project_visibility import (
            actor_visible_project_ids,
        )

        return sorted(actor_visible_project_ids(conn, int(actor_text)))
    return [
        int(row[0])
        for row in conn.execute("SELECT id FROM projects ORDER BY id").fetchall()
    ]


def _selected_project_ids(
    request: FunctionCallRequest,
    conn: Any,
    project: Optional[str],
) -> list[int]:
    visible = _visible_project_ids(request, conn)
    if not project:
        return visible
    from yoke_core.domain.project_identity import resolve_project

    identity = resolve_project(
        conn,
        project,
        required=False,
        visible_project_ids=visible,
    )
    if identity is None:
        raise LookupError(f"project {project!r} not found")
    return [identity.id]


def _markers(values: list[int]) -> str:
    return ", ".join("%s" for _ in values)


def _state_counts(conn: Any, project_ids: list[int]) -> Dict[str, int]:
    counts: Counter[str] = Counter(
        {
            "active": 0,
            "pipeline": 0,
            "backlog": 0,
            "blocked": 0,
            "frozen": 0,
            "done": 0,
            "unknown": 0,
        }
    )
    if not project_ids:
        return dict(counts)
    from yoke_core.domain.schema_common import _table_exists

    active_run = (
        "EXISTS("
        "SELECT 1 FROM deployment_run_items dri "
        "JOIN deployment_runs dr ON dr.id = dri.run_id "
        "WHERE dri.item_id = i.id AND dr.status IN ('created', 'executing')"
        ")"
        if (
            _table_exists(conn, "deployment_run_items")
            and _table_exists(conn, "deployment_runs")
        )
        else "FALSE"
    )
    # An epic stands for the work it contains, so the terminal board's
    # stats box counts it as its tasks rather than as one row. Match that
    # here or the two surfaces disagree on every universe using epics.
    task_units = (
        "(SELECT COUNT(*) FROM epic_tasks et WHERE et.epic_id = i.id)"
        if _table_exists(conn, "epic_tasks")
        else "0"
    )
    rows = conn.execute(
        "SELECT i.id, i.status, i.frozen, i.blocked, i.workflow_id, "
        f"{active_run} AS has_active_run, {task_units} AS task_units "
        f"FROM items i WHERE i.project_id IN ({_markers(project_ids)})",
        tuple(project_ids),
    ).fetchall()
    for row in rows:
        bucket = status_to_board_bucket(
            str(row["status"]),
            row["frozen"],
            bool(row["has_active_run"]),
            str(row["workflow_id"]),
            row["blocked"],
        )
        tasks = int(row["task_units"] or 0)
        expanded = tasks if str(row["workflow_id"]) == "epic" and tasks else 1
        counts[_STATE_GROUPS.get(bucket, "unknown")] += expanded
    return dict(counts)


def _day_counts(
    conn: Any,
    project_ids: list[int],
    *,
    start_day: str,
) -> dict[str, Counter[str]]:
    series: dict[str, Counter[str]] = defaultdict(Counter)
    if not project_ids:
        return series
    from yoke_core.domain.schema_common import _table_exists

    markers = _markers(project_ids)
    params = (*project_ids, start_day)
    if _table_exists(conn, "item_activity_days"):
        for row in conn.execute(
            "SELECT day, COUNT(DISTINCT item_id) AS total "
            "FROM item_activity_days "
            f"WHERE project_id IN ({markers}) AND day >= %s "
            "GROUP BY day",
            params,
        ).fetchall():
            series[str(row["day"])]["activity"] = int(row["total"])
    if _table_exists(conn, "item_status_transitions"):
        # Work inside an epic moves tasks, not the epic row, so a
        # task-only day registers no item activity at all without this.
        # Each (day, item, task) counts once, matching the board.
        for row in conn.execute(
            "SELECT day, COUNT(*) AS total FROM ("
            "  SELECT SUBSTRING(t.created_at, 1, 10) AS day, "
            "         t.item_id AS item_id, t.task_num AS task_num "
            "  FROM item_status_transitions t "
            f"  WHERE t.project_id IN ({markers}) "
            "  AND t.task_num IS NOT NULL "
            "  AND SUBSTRING(t.created_at, 1, 10) >= %s "
            "  GROUP BY 1, 2, 3"
            ") touched GROUP BY day",
            params,
        ).fetchall():
            series[str(row["day"])]["activity"] += int(row["total"])
    if _table_exists(conn, "item_status_transitions"):
        # Delivery, not intake: the board's issues meter counts work
        # reaching a terminal success, and counting items created instead
        # would trend opposite to it on any day of heavy grooming.
        for row in conn.execute(
            "SELECT SUBSTRING(t.created_at, 1, 10) AS day, COUNT(*) AS total "
            "FROM item_status_transitions t "
            f"WHERE t.project_id IN ({markers}) "
            "AND t.to_status IN ('done', 'passed') "
            "AND SUBSTRING(t.created_at, 1, 10) >= %s "
            "GROUP BY SUBSTRING(t.created_at, 1, 10)",
            params,
        ).fetchall():
            series[str(row["day"])]["issues"] = int(row["total"])
    if _table_exists(conn, "strategy_doc_revisions"):
        for row in conn.execute(
            "SELECT SUBSTRING(created_at, 1, 10) AS day, COUNT(*) AS total "
            "FROM strategy_doc_revisions "
            f"WHERE project_id IN ({markers}) "
            "AND SUBSTRING(created_at, 1, 10) >= %s "
            "GROUP BY SUBSTRING(created_at, 1, 10)",
            params,
        ).fetchall():
            series[str(row["day"])]["strategy"] = int(row["total"])
    if _table_exists(conn, "events"):
        for row in conn.execute(
            "SELECT SUBSTRING(created_at, 1, 10) AS day, COUNT(*) AS total "
            "FROM events "
            f"WHERE project_id IN ({markers}) "
            "AND SUBSTRING(created_at, 1, 10) >= %s "
            "AND (LOWER(COALESCE(event_type, '')) IN "
            "('git', 'github', 'pull_request', 'merge', 'code') "
            "OR LOWER(COALESCE(tool_name, '')) = 'git') "
            "GROUP BY SUBSTRING(created_at, 1, 10)",
            params,
        ).fetchall():
            series[str(row["day"])]["code"] = int(row["total"])
    return series


def handle_overview_vitals(request: FunctionCallRequest) -> HandlerOutcome:
    if request.target.kind != "global":
        return _error(
            "overview.vitals.get requires target.kind='global'",
            "$.target.kind",
        )
    try:
        payload = OverviewVitalsRequest.model_validate(request.payload or {})
    except Exception as exc:
        return _error(str(exc))
    if payload.days < 1 or payload.days > 365:
        return _error("days must be from 1 to 365", "$.payload.days")

    from yoke_core.domain.db_helpers import connect

    conn = connect()
    try:
        try:
            project_ids = _selected_project_ids(
                request,
                conn,
                payload.project,
            )
        except LookupError as exc:
            return HandlerOutcome(
                primary_success=False,
                error=FunctionError(
                    code="not_found",
                    message=str(exc),
                    jsonpath="$.payload.project",
                ),
            )
        today = datetime.now(timezone.utc).date()
        first = today - timedelta(days=payload.days - 1)
        counts = _day_counts(
            conn,
            project_ids,
            start_day=first.isoformat(),
        )
        momentum = []
        for offset in range(payload.days):
            day = (first + timedelta(days=offset)).isoformat()
            values = counts.get(day, {})
            momentum.append(
                {
                    "day": day,
                    "activity": int(values.get("activity", 0)),
                    "code": int(values.get("code", 0)),
                    "issues": int(values.get("issues", 0)),
                    "strategy": int(values.get("strategy", 0)),
                }
            )
        state_counts = _state_counts(conn, project_ids)
        strategy_timeline = _strategy_timelines(conn, project_ids)
    finally:
        conn.close()
    return HandlerOutcome(
        result_payload={
            "state_counts": state_counts,
            "momentum": momentum,
            "strategy_timeline": strategy_timeline,
            "days": payload.days,
        },
        primary_success=True,
    )


__all__ = [
    "OverviewVitalsRequest",
    "OverviewVitalsResponse",
    "handle_overview_vitals",
]
