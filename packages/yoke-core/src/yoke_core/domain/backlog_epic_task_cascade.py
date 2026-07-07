"""Backlog epic-task cascade — when an epic item's status changes, propagate
the change to its child tasks via `epic.cascade_task_status`.
"""

from __future__ import annotations

import sys
from typing import Any, TextIO

from yoke_core.domain.backlog_queries import _query_item_field


def _cascade_epic_tasks(
    conn: Any,
    item_id: int,
    old_status: str,
    new_status: str,
    out: TextIO = sys.stderr,
) -> None:
    """Cascade status change to epic tasks if item is an epic.

    Calls ``epic.cascade_task_status`` in-process through the canonical
    domain helper.
    """
    item_type = _query_item_field(conn, item_id, "type")
    if item_type != "epic":
        return

    from yoke_core.domain import epic as epic_domain

    try:
        result_text = epic_domain.cascade_task_status(
            conn, str(item_id), old_status, new_status
        )
    except Exception as exc:  # pragma: no cover - defensive
        print(f"Epic task cascade failed for YOK-{item_id}: {exc}", file=out)
        return

    count = (result_text or "").strip()
    if count and count != "0":
        print(
            f"Epic task cascade: YOK-{item_id} {old_status} -> {new_status}"
            f" -- {count} tasks updated",
            file=out,
        )


__all__ = ["_cascade_epic_tasks"]
