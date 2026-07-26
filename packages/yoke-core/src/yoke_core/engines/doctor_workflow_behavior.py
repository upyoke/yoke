"""Workflow-policy helpers shared by backlog health checks."""

from __future__ import annotations

from typing import Any, Iterable

from yoke_core.domain.workflow_behavior import generates_task_graph
from yoke_core.domain.workflow_runtime import load_workflow_runtime


def rows_generating_task_graph(conn: Any, rows: Iterable[Any]) -> list[Any]:
    """Keep rows whose immutable workflow pin generates task children."""
    cache: dict[tuple[str, int], bool] = {}
    selected: list[Any] = []
    for row in rows:
        workflow_id = str(row["workflow_id"] or "")
        version_id = row["workflow_version_id"]
        if not workflow_id or version_id is None:
            continue
        pin = (workflow_id, int(version_id))
        if pin not in cache:
            cache[pin] = generates_task_graph(
                load_workflow_runtime(
                    conn,
                    workflow_id=workflow_id,
                    workflow_version_id=int(version_id),
                )
            )
        if cache[pin]:
            selected.append(row)
    return selected


__all__ = ["rows_generating_task_graph"]
