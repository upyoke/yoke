"""Authoritative project roster summaries for the universe Projects screen."""

from __future__ import annotations

from collections import Counter
from typing import Any, Iterable

from yoke_contracts.item_flags import is_frozen
from yoke_core.domain.scheduler import compute_schedule
from yoke_core.domain.workflow_runtime import workflow_runtime_from_row


PROJECT_SUMMARY_BASE_FIELDS = (
    "id",
    "slug",
    "name",
    "emoji",
    "github_repo",
    "default_branch",
    "public_item_prefix",
)

PROJECT_SUMMARY_FIELDS = (
    "in_flight_count",
    "ready_count",
    "blocked_count",
    "strategy_doc_count",
    "has_strategy",
)


def _item_rows(conn: Any, project_ids: tuple[int, ...]) -> list[dict[str, Any]]:
    if not project_ids:
        return []
    markers = ", ".join("%s" for _ in project_ids)
    rows = conn.execute(
        "SELECT i.project_id, i.status, i.frozen, i.workflow_id, "
        "i.workflow_version_id, v.version, v.definition_json, "
        "v.definition_digest "
        "FROM items i JOIN workflow_versions v ON v.id = i.workflow_version_id "
        f"WHERE i.project_id IN ({markers})",
        project_ids,
    ).fetchall()
    return [dict(row) for row in rows]


def _strategy_counts(
    conn: Any,
    project_ids: tuple[int, ...],
) -> Counter[int]:
    if not project_ids:
        return Counter()
    markers = ", ".join("%s" for _ in project_ids)
    rows = conn.execute(
        "SELECT project_id, COUNT(*) AS doc_count FROM strategy_docs "
        f"WHERE project_id IN ({markers}) AND archived_at IS NULL "
        "GROUP BY project_id",
        project_ids,
    ).fetchall()
    return Counter({int(row["project_id"]): int(row["doc_count"]) for row in rows})


def enrich_project_summaries(
    conn: Any,
    rows: Iterable[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Add work and strategy aggregates with one scheduler pass."""
    projects = [dict(row) for row in rows]
    project_ids = tuple(int(row["id"]) for row in projects)
    if not project_ids:
        return []
    slug_by_id = {int(row["id"]): str(row.get("slug") or row["id"]) for row in projects}
    in_flight: Counter[str] = Counter()
    for item in _item_rows(conn, project_ids):
        if is_frozen(item.get("frozen")):
            continue
        workflow = workflow_runtime_from_row(item)
        stage_id = str(item["status"])
        if (
            workflow.stage_index(stage_id) is not None
            and stage_id not in workflow.terminal_stage_ids
            and not workflow.is_before_implementation(stage_id)
        ):
            in_flight[slug_by_id[int(item["project_id"])]] += 1

    schedule = compute_schedule(conn, list(project_ids), emit_events=False)
    ready = Counter(step.project for step in schedule.ranked_steps)
    blocked_items: dict[str, set[str]] = {}
    for step in schedule.blocked_steps:
        blocked_items.setdefault(step.project, set()).add(step.item_id)
    strategy = _strategy_counts(conn, project_ids)

    enriched: list[dict[str, Any]] = []
    for row in projects:
        project_id = int(row["id"])
        slug = str(row.get("slug") or project_id)
        doc_count = int(strategy[project_id])
        enriched.append(
            {
                **row,
                "in_flight_count": int(in_flight[slug]),
                "ready_count": int(ready[slug]),
                "blocked_count": len(blocked_items.get(slug, set())),
                "strategy_doc_count": doc_count,
                "has_strategy": doc_count > 0,
            }
        )
    return enriched


__all__ = [
    "PROJECT_SUMMARY_BASE_FIELDS",
    "PROJECT_SUMMARY_FIELDS",
    "enrich_project_summaries",
]
