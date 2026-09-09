"""Resolving a stored row's project so the title policy can be applied.

The shared policy in :mod:`yoke_contracts.title_policy` answers "how long
may a title be for this project". This module answers the question in front
of it for rows that already live in the database: which project owns them.
Epic tasks resolve through their parent item, because a task's project is
its epic's project.
"""

from __future__ import annotations

from typing import Any, Optional

from yoke_contracts.title_policy import TitleProject, title_length_error

from yoke_core.domain.epic_parsing import _placeholder


def item_project(conn: Any, item_id: Any) -> TitleProject:
    """The project owning *item_id*, or ``None`` when it cannot be read.

    An unreadable owner resolves to the default policy rather than
    refusing: minimal fixtures and pre-insert callers legitimately have no
    item row yet, and every project resolves to the same limit today.
    """
    try:
        row = conn.execute(
            f"SELECT project_id FROM items WHERE id={_placeholder(conn)}",
            (int(item_id),),
        ).fetchone()
    except Exception:  # noqa: BLE001 - an absent items table is not a title fault
        return None
    if row is None:
        return None
    value = row["project_id"] if not isinstance(row, tuple) else row[0]
    return None if value is None else int(value)


def item_title_length_error(
    conn: Any,
    item_id: Any,
    title: str,
    *,
    subject: str = "Title",
) -> Optional[str]:
    """Why *title* is too long for the project owning *item_id*."""
    return title_length_error(
        title,
        project=item_project(conn, item_id),
        subject=subject,
    )


__all__ = ["item_project", "item_title_length_error"]
