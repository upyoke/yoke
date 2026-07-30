"""Backlog epic-task cascade — when an epic item's status changes, propagate
the change to its child tasks via `epic.cascade_task_status`.
"""

from __future__ import annotations

import sys
from typing import Any, TextIO

from yoke_core.domain.workflow_behavior import generates_task_graph
from yoke_core.domain.workflow_runtime import load_item_workflow_runtime


def _cascade_epic_tasks(
    conn: Any,
    item_id: int,
    old_status: str,
    new_status: str,
    out: TextIO = sys.stderr,
    *,
    commit: bool = True,
    strict: bool = False,
) -> None:
    """Cascade status change to epic tasks if item is an epic.

    Calls ``epic.cascade_task_status`` in-process through the canonical
    domain helper.
    """
    if not generates_task_graph(load_item_workflow_runtime(conn, item_id)):
        return

    from yoke_core.domain import epic as epic_domain
    from yoke_core.domain.project_identity import render_item_ref

    # Rendered once here while the connection is healthy so the failure
    # branch below does not issue a query against a possibly-aborted
    # transaction.
    item_ref = render_item_ref(conn, item_id)

    try:
        result_text = epic_domain.cascade_task_status(
            conn,
            str(item_id),
            old_status,
            new_status,
            commit=commit,
        )
    except Exception as exc:  # pragma: no cover - defensive
        if strict:
            raise
        print(f"Epic task cascade failed for {item_ref}: {exc}", file=out)
        return

    count = (result_text or "").strip()
    if count and count != "0":
        print(
            f"Epic task cascade: {item_ref} {old_status} -> {new_status}"
            f" -- {count} tasks updated",
            file=out,
        )


__all__ = ["_cascade_epic_tasks"]
