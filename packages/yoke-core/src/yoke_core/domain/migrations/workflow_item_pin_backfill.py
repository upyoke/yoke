"""Backfill every existing item to its immutable built-in workflow version."""

from __future__ import annotations

from typing import Any

from yoke_core.domain.workflow_item_pins import (
    backfill_legacy_item_workflow_pins,
)
from yoke_core.domain.workflow_registry import (
    converge_builtin_workflows,
)
from yoke_core.domain.workflow_runtime import (
    ENGINE_EXCEPTIONAL_STAGE_IDS,
    load_item_workflow_runtime,
)
from yoke_core.domain.workflow_schema import ensure_workflow_schema

MIGRATION_NAME = "workflow_item_pin_backfill"


def apply(conn: Any) -> None:
    """Pin every unpinned legacy item without changing its current stage."""
    ensure_workflow_schema(conn)
    converge_builtin_workflows(conn)
    backfill_legacy_item_workflow_pins(conn)
    conn.commit()


def invariants(conn: Any) -> None:
    """Verify complete pins, matching versions, and stage membership."""
    invalid = conn.execute(
        "SELECT i.id FROM items i "
        "LEFT JOIN workflow_versions v ON v.id = i.workflow_version_id "
        "WHERE i.workflow_id IS NULL OR i.workflow_version_id IS NULL "
        "OR v.id IS NULL OR v.workflow_id <> i.workflow_id "
        "ORDER BY i.id LIMIT 5"
    ).fetchall()
    if invalid:
        samples = ", ".join(str(row[0]) for row in invalid)
        raise AssertionError(f"items have invalid workflow pins: {samples}")

    rows = conn.execute("SELECT id, status FROM items ORDER BY id").fetchall()
    for item_id, status in rows:
        runtime = load_item_workflow_runtime(conn, int(item_id))
        stage_id = str(status)
        if (
            stage_id not in runtime.stage_ids
            and stage_id not in ENGINE_EXCEPTIONAL_STAGE_IDS
        ):
            raise AssertionError(
                f"item {item_id} stage {stage_id!r} is not valid for "
                f"{runtime.workflow_id}@{runtime.version}"
            )


__all__ = ["MIGRATION_NAME", "apply", "invariants"]
