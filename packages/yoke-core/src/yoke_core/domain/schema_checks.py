"""Validation checks for the canonical Yoke control-plane schema.

Item stages are validated through immutable workflow pins. Epic-task statuses
retain their engine-owned vocabulary.
"""

from __future__ import annotations

import sys
from typing import Any

# Canonical epic_tasks statuses
_VALID_TASK_STATUSES = (
    "planning", "plan-drafted", "refining-plan", "planned", "implementing",
    "reviewing-implementation", "reviewed-implementation",
    "polishing-implementation", "implemented", "release", "done",
    "failed", "blocked", "stopped",
)

_VALID_TASK_STATUSES_SQL = ", ".join(f"'{s}'" for s in _VALID_TASK_STATUSES)


# ---------------------------------------------------------------------------
# Validators
# ---------------------------------------------------------------------------

def _validate_item_workflow_stages(conn: Any) -> None:
    """Verify every item stage against its immutable workflow pin."""
    from yoke_core.domain.workflow_runtime import (
        ENGINE_EXCEPTIONAL_STAGE_IDS,
        load_item_workflow_runtime,
    )
    from yoke_core.domain.workflow_registry import WorkflowRegistryError

    invalid: list[str] = []
    rows = conn.execute("SELECT id, status FROM items ORDER BY id").fetchall()
    for item_id, status in rows:
        try:
            runtime = load_item_workflow_runtime(conn, int(item_id))
        except WorkflowRegistryError as exc:
            invalid.append(f"{item_id}|{exc}")
            continue
        stage_id = str(status)
        if (
            stage_id not in runtime.stage_ids
            and stage_id not in ENGINE_EXCEPTIONAL_STAGE_IDS
        ):
            invalid.append(
                f"{item_id}|{stage_id} not in "
                f"{runtime.workflow_id}@{runtime.version}"
            )
    if invalid:
        print(
            f"Error: {len(invalid)} items have invalid workflow stages:",
            file=sys.stderr,
        )
        for evidence in invalid:
            print(evidence, file=sys.stderr)
        sys.exit(1)


def _validate_epic_task_statuses(conn: Any) -> None:
    """Verify no epic_tasks have retired/invalid statuses."""
    cur = conn.execute(
        f"SELECT COUNT(*) FROM epic_tasks WHERE status NOT IN ({_VALID_TASK_STATUSES_SQL})"
    )
    count = cur.fetchone()[0]
    if count > 0:
        print(f"Error: {count} epic_tasks have retired/invalid statuses:", file=sys.stderr)
        rows = conn.execute(
            f"SELECT epic_id || ':' || task_num || '|' || status FROM epic_tasks "
            f"WHERE status NOT IN ({_VALID_TASK_STATUSES_SQL}) ORDER BY epic_id, task_num"
        ).fetchall()
        for row in rows:
            print(row[0], file=sys.stderr)
        print("Error: epic_tasks contain retired statuses that are no longer valid.", file=sys.stderr)
        sys.exit(1)
