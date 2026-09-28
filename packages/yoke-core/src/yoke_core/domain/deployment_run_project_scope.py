"""Select whole runs by the projects represented in their membership."""

from __future__ import annotations

from collections.abc import Collection
from typing import Any

from yoke_core.domain import db_backend


def run_project_scope(
    conn: Any, project_ids: Collection[int] | None
) -> tuple[list[str], list[int]]:
    """Match a member's project, or an itemless run's owning project."""
    if project_ids is None:
        return [], []
    ids = sorted({int(value) for value in project_ids})
    if not ids:
        return ["1 = 0"], []
    marker = "%s" if db_backend.connection_is_postgres(conn) else "?"
    markers = ", ".join(marker for _ in ids)
    clause = (
        "(EXISTS (SELECT 1 FROM deployment_run_items dri "
        "JOIN items i ON i.id=dri.item_id WHERE dri.run_id=dr.id "
        f"AND i.project_id IN ({markers})) OR "
        f"(dr.project_id IN ({markers}) AND NOT EXISTS "
        "(SELECT 1 FROM deployment_run_items dri WHERE dri.run_id=dr.id)))"
    )
    return [clause], [*ids, *ids]


__all__ = ["run_project_scope"]
