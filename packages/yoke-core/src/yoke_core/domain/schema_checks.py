"""Schema validation checks for yoke.db.

Status validity checks for items and epic_tasks, extracted from schema.py.
Callers import these from schema.py which re-exports them.
"""

from __future__ import annotations

import sys
from typing import Any

# ---------------------------------------------------------------------------
# Status constants (canonical — imported back into schema.py)
# ---------------------------------------------------------------------------

# Canonical item statuses.
# "blocked" is retained in the CHECK constraint enum here so legacy
# rows can continue to round-trip through the DB during the migration window.
# Post-cutover, no fresh write produces status='blocked' for items — the
# canonical signal is items.blocked=1, and HC-blocked-status-drift surfaces
# any row that still holds the legacy lifecycle position.
_VALID_ITEM_STATUSES = (
    "idea", "planned", "release", "done", "cancelled", "blocked",
    "stopped", "failed", "refining-idea", "refined-idea", "implementing",
    "reviewing-implementation", "reviewed-implementation",
    "polishing-implementation", "implemented", "planning",
    "plan-drafted", "refining-plan",
)

_VALID_ITEM_STATUSES_SQL = ", ".join(f"'{s}'" for s in _VALID_ITEM_STATUSES)

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

def _validate_item_statuses(conn: Any) -> None:
    """Verify no items have retired/invalid statuses."""
    cur = conn.execute(
        f"SELECT COUNT(*) FROM items WHERE status NOT IN ({_VALID_ITEM_STATUSES_SQL})"
    )
    count = cur.fetchone()[0]
    if count > 0:
        print(f"Error: {count} items have retired/invalid statuses:", file=sys.stderr)
        rows = conn.execute(
            f"SELECT id || '|' || status FROM items "
            f"WHERE status NOT IN ({_VALID_ITEM_STATUSES_SQL}) ORDER BY id"
        ).fetchall()
        for row in rows:
            print(row[0], file=sys.stderr)
        print(
            "Run the zero-legacy DB convergence tool to fix these before proceeding.",
            file=sys.stderr,
        )
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
