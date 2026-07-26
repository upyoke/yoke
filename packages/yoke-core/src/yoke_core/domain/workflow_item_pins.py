"""Compatibility convergence for immutable workflow pins on legacy items."""

from __future__ import annotations

from typing import Any

from yoke_core.domain import db_backend
from yoke_core.domain.schema_common import _column_exists
from yoke_core.domain.workflow_registry import resolve_current_workflow_pin

_LEGACY_WORKFLOW_IDS = ("epic", "issue")


def _placeholder(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def backfill_legacy_item_workflow_pins(conn: Any) -> int:
    """Pin every unpinned legacy item without changing its current stage.

    The helper remains on the boot-convergence path after the cutover. It is
    therefore deliberately idempotent: once the legacy ``items.type`` column
    has been contracted, a fully pinned database is a no-op.
    """
    partial = conn.execute(
        "SELECT id FROM items "
        "WHERE (workflow_id IS NULL) <> (workflow_version_id IS NULL) "
        "ORDER BY id LIMIT 5"
    ).fetchall()
    if partial:
        samples = ", ".join(str(row[0]) for row in partial)
        raise RuntimeError(f"items have partial workflow pins: {samples}")

    if not _column_exists(conn, "items", "type"):
        unpinned = conn.execute(
            "SELECT id FROM items "
            "WHERE workflow_id IS NULL OR workflow_version_id IS NULL "
            "ORDER BY id LIMIT 5"
        ).fetchall()
        if unpinned:
            samples = ", ".join(str(row[0]) for row in unpinned)
            raise RuntimeError(
                "items lack workflow pins after legacy classification "
                f"retirement: {samples}"
            )
        return 0

    marker = _placeholder(conn)
    changed = 0
    for workflow_id in _LEGACY_WORKFLOW_IDS:
        _, version_id = resolve_current_workflow_pin(conn, workflow_id)
        cursor = conn.execute(
            "UPDATE items SET workflow_id = "
            f"{marker}, workflow_version_id = {marker} "
            "WHERE workflow_id IS NULL AND workflow_version_id IS NULL "
            f"AND type = {marker}",
            (workflow_id, version_id, workflow_id),
        )
        changed += max(int(cursor.rowcount or 0), 0)

    unknown = conn.execute(
        "SELECT id, type FROM items "
        "WHERE workflow_id IS NULL OR workflow_version_id IS NULL "
        "ORDER BY id LIMIT 5"
    ).fetchall()
    if unknown:
        samples = ", ".join(f"{row[0]}:{row[1]}" for row in unknown)
        raise RuntimeError("items cannot be mapped to built-in workflows: " + samples)
    return changed


__all__ = ["backfill_legacy_item_workflow_pins"]
