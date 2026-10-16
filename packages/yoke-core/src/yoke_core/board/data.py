"""Collect named board facts for local and HTTPS clients."""

from __future__ import annotations

from yoke_contracts.board.data import BOARD_DATA_VERSION, BoardDataError, _encode_value
from yoke_contracts.board.project_scope import project_filter, scoped_project_visibility
from yoke_contracts.board.sections import (
    classify_items,
    frontier_counts,
    precompute_epic_stats,
    precompute_epic_task_rows,
    task_expanded_count,
)
from yoke_contracts.board.renderer_dashboard import collect_dashboard_data
from yoke_contracts.board.sections_sessions import collect_session_rows
from yoke_contracts.board.sections_sessions_occupancy import prefetch_session_occupancy
from yoke_contracts.board.sections_architecture import collect_architecture_rows
from yoke_contracts.board.zen_data import _zen_check_visibility
from yoke_contracts.board.zen_render import collect_timeline_rows


def collect_board_data(
    db,
    *,
    scope,
    config,
    repo_root=None,
    vision_entries=(),
    vision_project=None,
    visible_project_ids=None,
) -> dict:
    """Read authorized facts once; no board rendering or SQL enters the payload."""
    visible = (
        None
        if visible_project_ids is None
        else tuple(sorted(set(map(int, visible_project_ids))))
    )
    db._activity_day_counts_cache = {}
    db._board_model_catalogs = {}
    with scoped_project_visibility(visible):
        stats = precompute_epic_stats(db, scope)
        buckets = classify_items(db, scope, epic_stats=stats)
        task_counts = {eid: stat.task_count for eid, stat in stats.items()}
        tasks = precompute_epic_task_rows(db, scope) if task_counts else {}
        counts = {
            key: task_expanded_count(rows, task_counts) for key, rows in buckets.items()
        }
        pf, params = project_filter(scope)
        max_id = db.scalar("SELECT MAX(id) FROM items WHERE 1=1" + pf, params)
        sessions_scope = config.dashboard_sessions_scope or scope
        prefetch_session_occupancy(db, scope)
        timeline = []
        if _zen_check_visibility(
            config.timeline_widget,
            counts["active"],
            counts["pipeline"],
            counts["backlog"],
        ):
            timeline = collect_timeline_rows(
                db,
                config,
                config.timeline_scope or scope,
                vision_count=len(list(vision_entries)),
                vision_project=vision_project,
            )
        data = {
            "version": BOARD_DATA_VERSION,
            "scope": scope,
            "vision_project": vision_project,
            "items": {
                key: [row._asdict() for row in rows] for key, rows in buckets.items()
            },
            "epics": [
                {
                    "id": eid,
                    "task_count": count,
                    "tasks": [
                        {
                            "id": row[0],
                            "title": row[1],
                            "status": row[2],
                            "status_glyph": row[3],
                        }
                        for row in tasks.get(eid, ())
                    ],
                }
                for eid, count in task_counts.items()
            ],
            "max_id_width": len(str(max_id or 0)) + 4,
            "frontier": frontier_counts(db, scope, config.art_frontier_since),
            "dashboard": collect_dashboard_data(
                db, config, scope, counts["done"], repo_root
            ),
            "timeline": timeline,
            "sessions": {
                "active": collect_session_rows(
                    db, scope=sessions_scope, active_only=True
                ),
                "recent": collect_session_rows(
                    db, scope=sessions_scope, active_only=False
                )
                if config.dashboard_recent_sessions
                else [],
            },
            "architecture": collect_architecture_rows(db, scope),
        }
    return _encode_value(data)


__all__ = ["BOARD_DATA_VERSION", "BoardDataError", "collect_board_data"]
