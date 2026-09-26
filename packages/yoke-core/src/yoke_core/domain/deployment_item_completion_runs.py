"""Every deployment run whose membership is completion authority for an item.

One walk, several readers. The done gate's delivery fact, the QA source
obligation, the delivery-evidence ladder and the release-wait close-out all
ask "which runs could close this item", and a copy of that walk per reader is
how the facts loader once counted only the item's own flow while the ladder
beside it also honoured a cross-project carrier — one release, two answers.

A membership closes the item when :func:`membership_closes_item` says so: a
run of the item's own completion flow, or another project's run that recorded
a bound source commit for the item's project. Carried code alone, or a
same-project run of any other flow, is membership without authority.
"""

from __future__ import annotations

from typing import Any

from yoke_core.domain import db_backend
from yoke_core.domain.deployment_item_flow_resolution import (
    item_completion_flow,
    membership_closes_item,
)
from yoke_core.domain.deployment_run_bound_sources import BOUND_SOURCES_FIELD
from yoke_core.domain.deployment_run_project_sources import recorded_source_sha
from yoke_core.domain.schema_common import _column_exists, _table_exists


def _row_value(row: Any, key: str, position: int) -> Any:
    return row[key] if hasattr(row, "keys") else row[position]


def _bound_sources_column(conn: Any) -> str:
    """Select the recorded bound sources, or empty on an unconverged plane."""
    if _column_exists(conn, "deployment_runs", BOUND_SOURCES_FIELD):
        return f"COALESCE(dr.{BOUND_SOURCES_FIELD}, '') AS {BOUND_SOURCES_FIELD}"
    return f"'' AS {BOUND_SOURCES_FIELD}"


def completion_runs(conn: Any, item_id: int) -> list[dict[str, Any]]:
    """Newest-first memberships that can close this item, of any status.

    Freshness is ``created_at`` (then ``id``). ``release_lineage`` and
    ``project_id`` name the candidate to ask containment about: the commit
    the run recorded for THIS item's project, which for an own-project run
    is the run's own lineage and for a carrier is the bound commit.
    """
    required = ("deployment_runs", "deployment_run_items")
    if not all(_table_exists(conn, table) for table in required):
        return []
    flow = item_completion_flow(conn, int(item_id))
    if not flow:
        return []
    marker = "%s" if db_backend.connection_is_postgres(conn) else "?"
    rows = conn.execute(
        "SELECT dr.id, dr.status, dr.current_stage, dr.project_id, "
        "COALESCE(dr.release_lineage, '') AS release_lineage, dr.flow, "
        "i.project_id AS item_project_id, "
        f"{_bound_sources_column(conn)} "
        "FROM deployment_runs dr "
        "JOIN deployment_run_items dri ON dr.id = dri.run_id "
        "JOIN items i ON i.id = dri.item_id "
        f"WHERE dri.item_id = {marker} "
        "ORDER BY dr.created_at DESC, dr.id DESC",
        (int(item_id),),
    ).fetchall()
    closing: list[dict[str, Any]] = []
    for row in rows:
        item_project = int(_row_value(row, "item_project_id", 6))
        source_sha = recorded_source_sha(
            {
                "project_id": _row_value(row, "project_id", 3),
                "release_lineage": _row_value(row, "release_lineage", 4),
                BOUND_SOURCES_FIELD: _row_value(row, BOUND_SOURCES_FIELD, 7),
            },
            item_project,
        )
        run_flow = str(_row_value(row, "flow", 5) or "")
        if not membership_closes_item(
            run_flow=run_flow,
            completion_flow=flow,
            run_project_id=int(_row_value(row, "project_id", 3)),
            item_project_id=item_project,
            source_sha=source_sha,
        ):
            continue
        closing.append(
            {
                "id": str(_row_value(row, "id", 0) or ""),
                "status": str(_row_value(row, "status", 1) or ""),
                "current_stage": str(_row_value(row, "current_stage", 2) or ""),
                "project_id": item_project,
                "release_lineage": source_sha,
                "flow": run_flow,
            }
        )
    return closing


def succeeded_completion_runs(conn: Any, item_id: int) -> list[dict[str, Any]]:
    """The closing memberships whose run succeeded — delivery that happened."""
    return [run for run in completion_runs(conn, item_id) if run["status"] == "succeeded"]


__all__ = ["completion_runs", "succeeded_completion_runs"]
