"""Additive learning-log columns for observing vs target project.

A field note carries two project facts that were one column for as long
as they always agreed: where the observing session was standing, and
where the fix belongs. They disagree whenever an agent notices a defect
in one repo while working from another, and the promotion that follows
files the item wherever the note happened to be attributed.

``project_id`` stays the observing project and is still resolved
automatically from the calling checkout. ``target_project_id`` is the
author's optional declaration of where the fix deploys, and is what
promotion prefers. ``project_override`` records a promotion that named a
target project of its own, so the routing decision survives on the
disposition row rather than only in the item it produced.
"""

from __future__ import annotations

from typing import Any

from yoke_core.domain.schema_common import _add_column_if_not_exists


def apply_ouroboros_columns(conn: Any) -> None:
    """Converge the learning-log project columns onto an existing universe."""
    _add_column_if_not_exists(
        conn, "ouroboros_entries", "target_project_id", "INTEGER DEFAULT NULL"
    )
    _add_column_if_not_exists(
        conn,
        "ouroboros_entry_dispositions",
        "project_override",
        "TEXT DEFAULT NULL",
    )
    conn.commit()


__all__ = ["apply_ouroboros_columns"]
