"""Frontier counts and the post-render consistency check.

Owns ``frontier_counts`` — the task-expanded per-status aggregate the
header dashboard renders — and ``consistency_check``, which validates
the rendered board's task sub-row count against the DB's expected total.
"""

from __future__ import annotations

from typing import Dict, Tuple

from yoke_contracts.board.board_db import BoardDBLike
from yoke_contracts.board.project_scope import project_filter

# ---------------------------------------------------------------------------
# Frontier counts
# ---------------------------------------------------------------------------


def frontier_counts(
    db: BoardDBLike,
    scope: str,
    art_frontier_since: int = 0,
) -> Dict[str, int]:
    """Compute task-expanded per-status frontier counts.

    Epic tasks count individually. Completed tasks count as their own
    status regardless of parent, non-completed tasks inherit parent
    item status, and items without tasks count as one unit at their own
    status.

    Args:
        db: Open database handle.
        scope: Project scope for filtering.
        art_frontier_since: Item ID threshold (0 = all items).

    Returns:
        Dict with keys: ``done``, ``implementing``, ``blocked``,
        ``reviewing``, ``release``, ``implemented``, ``refined``,
        ``idea``, ``planning``, ``total``.
    """
    import json
    from yoke_contracts.lifecycle_status import (
        ENGINE_TERMINAL_STAGE_IDS,
        LEGACY_STATUS_BUCKETS,
        successful_task_stage_ids,
    )
    from yoke_contracts.board.status import status_to_board_bucket

    counts = dict.fromkeys(
        (
            "done",
            "implementing",
            "blocked",
            "reviewing",
            "release",
            "implemented",
            "refined",
            "idea",
            "planning",
            "total",
        ),
        0,
    )
    pf, params = project_filter(scope, "i")
    since = f" AND i.id >= {int(art_frontier_since)}" if art_frontier_since > 0 else ""
    rows = db.query_quiet(
        f"""SELECT i.id, i.status, i.blocked, i.workflow_version_id,
                   v.definition_json, et.status, COUNT(et.task_num)
            FROM items i JOIN workflow_versions v ON v.id=i.workflow_version_id
            LEFT JOIN epic_tasks et ON et.epic_id=i.id
            WHERE COALESCE(i.frozen,0) <> 1 {pf}{since}
            GROUP BY i.id, i.status, i.blocked, i.workflow_version_id, v.definition_json, et.status""",
        params,
    )
    definitions = {}
    for _, status, blocked, version_id, raw, task_status, task_count in rows:
        if (
            status in ENGINE_TERMINAL_STAGE_IDS
            and LEGACY_STATUS_BUCKETS[status] == "done"
        ):
            continue
        if version_id not in definitions:
            definitions[version_id] = json.loads(raw) if isinstance(raw, str) else raw
        definition = definitions[version_id]
        effective = (
            task_status
            if task_status in successful_task_stage_ids(definition)
            else status
        )
        bucket = status_to_board_bucket(
            effective, False, blocked_value=blocked, workflow_definition=definition
        )
        weight = int(task_count) or 1
        counts["total"] += weight
        if bucket in counts:
            counts[bucket] += weight
    return counts


# ---------------------------------------------------------------------------
# Consistency check
# ---------------------------------------------------------------------------


def consistency_check(
    expected_tasks: int,
    board_content: str,
) -> Tuple[bool, str]:
    """Check that task sub-row count in rendered board matches expected.

    Counts lines containing the unicode left-corner character (U+2514, ``└``)
    which marks task sub-rows, and compares to the expected count from DB.

    Args:
        expected_tasks: Expected number of task sub-rows from DB.
        board_content: Rendered board markdown content.

    Returns:
        Tuple of (ok, message). ok is True when counts match.
    """
    actual = sum(1 for line in board_content.splitlines() if "└" in line)
    if actual == expected_tasks:
        return True, f"Task sub-row count OK: {actual}"
    return False, f"Task sub-row mismatch: expected {expected_tasks}, found {actual}"
