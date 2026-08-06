"""Authoritative state and momentum facts for the universe Overview.

These are the same signals the terminal board prints, so the two have to
agree: an operator reading `yoke board` and the same universe's Overview
must not see different numbers for the same scope. Momentum series and
streak facts come from :mod:`yoke_core.domain.board_momentum_signals`.
"""

from __future__ import annotations

from collections import Counter
from typing import Any, Dict, List, Optional

from pydantic import BaseModel

from yoke_contracts.api.function_call import (
    FunctionCallRequest,
    FunctionError,
    HandlerOutcome,
)
from yoke_contracts.board.status import status_to_board_bucket
from yoke_core.domain.workflow_runtime import workflow_runtime_from_row


class OverviewVitalsRequest(BaseModel):
    project: Optional[str] = None
    days: int = 120


class OverviewVitalsResponse(BaseModel):
    state_counts: Dict[str, int]
    momentum: List[Dict[str, Any]]
    zen: List[Dict[str, Any]]
    days: int
    streak_days: int = 0
    lifetime_pct: Optional[float] = None
    project_days: int = 0


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
    # A task-graph workflow stands for the work it contains, so the terminal
    # board's stats box counts it as its tasks rather than as one row.
    task_units = (
        "(SELECT COUNT(*) FROM epic_tasks et WHERE et.epic_id = i.id)"
        if _table_exists(conn, "epic_tasks")
        else "0"
    )
    rows = conn.execute(
        "SELECT i.id, i.status, i.frozen, i.blocked, "
        "i.workflow_id, i.workflow_version_id, v.version, "
        "v.definition_json, v.definition_digest, "
        f"{active_run} AS has_active_run, {task_units} AS task_units "
        "FROM items i "
        "JOIN workflow_versions v ON v.id = i.workflow_version_id "
        f"WHERE i.project_id IN ({_markers(project_ids)})",
        tuple(project_ids),
    ).fetchall()
    for row in rows:
        workflow = workflow_runtime_from_row(row)
        bucket = status_to_board_bucket(
            str(row["status"]),
            row["frozen"],
            bool(row["has_active_run"]),
            blocked_value=row["blocked"],
            workflow_definition=workflow.definition,
        )
        tasks = int(row["task_units"] or 0)
        expands_tasks = workflow.policies.get("generated_children") == "epic_tasks"
        expanded = tasks if expands_tasks and tasks else 1
        counts[_STATE_GROUPS.get(bucket, "unknown")] += expanded
    return dict(counts)


def _day_counts(
    conn: Any,
    project_ids: list[int],
    *,
    start_day: str,
) -> dict[str, Counter[str]]:
    """Thin adapter over shared momentum readers (kept for older tests)."""
    from collections import defaultdict

    from yoke_core.domain.board_momentum_signals import (
        activity_units_by_day,
        issues_done_by_day,
        strategy_bytes_by_day,
    )

    series: dict[str, Counter[str]] = defaultdict(Counter)
    for day, total in activity_units_by_day(
        conn, project_ids, start_day=start_day,
    ).items():
        series[day]["activity"] = total
    for day, total in issues_done_by_day(
        conn, project_ids, start_day=start_day,
    ).items():
        series[day]["issues"] = total
    for day, total in strategy_bytes_by_day(
        conn, project_ids, start_day=start_day,
    ).items():
        series[day]["strategy"] = total
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

    from yoke_core.domain.board_momentum_signals import build_momentum_series
    from yoke_core.domain.board_policy_read import resolve_board_config
    from yoke_core.domain.board_zen_signals import build_zen_payloads
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
        momentum, streak_facts = build_momentum_series(
            conn,
            project_ids,
            days=payload.days,
        )
        state_counts = _state_counts(conn, project_ids)
        settings_project_id = project_ids[0] if project_ids else None
        zen = build_zen_payloads(
            conn,
            project_ids,
            config=resolve_board_config(conn, settings_project_id),
        )
    finally:
        conn.close()
    return HandlerOutcome(
        result_payload={
            "state_counts": state_counts,
            "momentum": momentum,
            "zen": zen,
            "days": payload.days,
            "streak_days": int(streak_facts.get("streak_days") or 0),
            "lifetime_pct": streak_facts.get("lifetime_pct"),
            "project_days": int(streak_facts.get("project_days") or 0),
        },
        primary_success=True,
    )


__all__ = [
    "OverviewVitalsRequest",
    "OverviewVitalsResponse",
    "handle_overview_vitals",
]
