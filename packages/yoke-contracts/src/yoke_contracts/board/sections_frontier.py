"""Frontier counts and the post-render consistency check.

Owns ``frontier_counts`` — the task-expanded per-status aggregate the
header dashboard renders — and ``consistency_check``, which validates
the rendered board's task sub-row count against the DB's expected total.
"""

from __future__ import annotations

from typing import Dict, Tuple

from yoke_contracts.board.board_db import BoardDBLike
from yoke_contracts.board.sections_classify import _project_filter_sql
from yoke_contracts.lifecycle_status import TASK_TERMINAL_SUCCESS

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
    pf = _project_filter_sql(scope, db=db)
    since_filter = f"AND i.id >= {art_frontier_since}" if art_frontier_since > 0 else ""
    _tts_in = ", ".join(f"'{s}'" for s in sorted(TASK_TERMINAL_SUCCESS))

    # The blocked-flag column on items partitions an item into the blocked
    # bucket regardless of its lifecycle status. The legacy `status='blocked'`
    # branch is preserved (for the `eff_status IN ('blocked','stopped','failed')`
    # leg) so a row that still holds the legacy lifecycle position counts as
    # blocked too — drift detection is the doctor's job; the board renders
    # consistently across the cutover. `i.blocked = 1` is propagated as
    # `is_blocked_flag` so downstream stats can count blocked-flagged items
    # whose effective status is not the legacy blocked token.
    sql = f"""
    WITH task_counts AS (
        SELECT et.epic_id, et.status AS task_status, COUNT(*) AS cnt
        FROM epic_tasks et
        JOIN items i ON i.id = et.epic_id
        WHERE i.frozen <> 1 AND i.status <> 'cancelled'{pf} {since_filter}
        GROUP BY et.epic_id, et.status
    ), item_or_task AS (
        SELECT CASE
            WHEN tc.task_status IN ({_tts_in}) THEN tc.task_status
            WHEN tc.task_status IS NOT NULL THEN i.status
            ELSE i.status END AS eff_status,
        i.type AS item_type,
        CASE WHEN i.blocked = 1 THEN 1 ELSE 0 END AS is_blocked_flag,
        COALESCE(tc.cnt, 1) AS weight
        FROM items i LEFT JOIN task_counts tc ON tc.epic_id = i.id
        WHERE i.frozen <> 1 AND i.status <> 'cancelled'{pf} {since_filter}
    )
    SELECT
        COALESCE(SUM(CASE WHEN eff_status = 'done' THEN weight ELSE 0 END), 0),
        COALESCE(SUM(CASE WHEN is_blocked_flag = 0 AND eff_status = 'implementing'
                           OR (is_blocked_flag = 0 AND eff_status = 'reviewing-implementation' AND item_type = 'epic')
                          THEN weight ELSE 0 END), 0),
        COALESCE(SUM(CASE WHEN is_blocked_flag = 1
                           OR eff_status IN ('blocked','stopped','failed')
                          THEN weight ELSE 0 END), 0),
        COALESCE(SUM(CASE WHEN is_blocked_flag = 0 AND (eff_status IN ('reviewed-implementation','polishing-implementation')
                           OR (eff_status = 'reviewing-implementation' AND item_type <> 'epic'))
                          THEN weight ELSE 0 END), 0),
        COALESCE(SUM(CASE WHEN is_blocked_flag = 0 AND eff_status = 'release' THEN weight ELSE 0 END), 0),
        COALESCE(SUM(CASE WHEN is_blocked_flag = 0 AND eff_status = 'implemented' THEN weight ELSE 0 END), 0),
        COALESCE(SUM(CASE WHEN is_blocked_flag = 0 AND eff_status IN ('planned','refined-idea') AND item_type <> 'epic'
                          THEN weight ELSE 0 END), 0),
        COALESCE(SUM(CASE WHEN is_blocked_flag = 0 AND eff_status = 'idea' THEN weight ELSE 0 END), 0),
        COALESCE(SUM(CASE WHEN is_blocked_flag = 0 AND (eff_status IN ('refining-idea','planning','plan-drafted','refining-plan')
                           OR (eff_status = 'refined-idea' AND item_type = 'epic'))
                          THEN weight ELSE 0 END), 0),
        COALESCE(SUM(weight), 0)
    FROM item_or_task
    """
    rows = db.query_quiet(sql)

    if not rows or not rows[0]:
        return {
            "done": 0,
            "implementing": 0,
            "blocked": 0,
            "reviewing": 0,
            "release": 0,
            "implemented": 0,
            "refined": 0,
            "idea": 0,
            "planning": 0,
            "total": 0,
        }

    r = rows[0]
    return {
        "done": int(r[0]),
        "implementing": int(r[1]),
        "blocked": int(r[2]),
        "reviewing": int(r[3]),
        "release": int(r[4]),
        "implemented": int(r[5]),
        "refined": int(r[6]),
        "idea": int(r[7]),
        "planning": int(r[8]),
        "total": int(r[9]),
    }


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
