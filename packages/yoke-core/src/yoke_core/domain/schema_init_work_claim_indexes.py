"""Partial unique indexes that enforce active work-claim exclusivity.

Sibling-extracted from ``schema_init_tables`` so the active-uniqueness
contract has a responsibility-named home. The base ``work_claims`` table
DDL still lives in ``schema_init_tables.create_core_tables``; this
module owns the partial unique indexes that make the
"one active claim per work unit" invariant a storage-level guarantee.

Invariants enforced (all scoped to ``released_at IS NULL`` so historical
released overlap rows remain queryable evidence):

- ``idx_work_claims_active_item`` — one active claim per ``item_id``
  for rows where ``target_kind='item'``.
- ``idx_work_claims_active_epic_task`` — one active claim per
  ``(epic_id, task_num)`` for rows where ``target_kind='epic_task'``.
- ``idx_work_claims_active_process_conflict`` — unchanged process
  conflict-group invariant retained in ``schema_init_tables``. It stays
  in the base DDL because the table's CHECK constraint already binds
  ``conflict_group`` to ``target_kind='process'``; no migration was
  ever needed there.
"""

from __future__ import annotations

from typing import Any

ACTIVE_ITEM_INDEX_NAME = "idx_work_claims_active_item"
ACTIVE_EPIC_TASK_INDEX_NAME = "idx_work_claims_active_epic_task"

ACTIVE_ITEM_INDEX_DDL = (
    "CREATE UNIQUE INDEX IF NOT EXISTS "
    f"{ACTIVE_ITEM_INDEX_NAME} "
    "ON work_claims(item_id) "
    "WHERE released_at IS NULL AND target_kind='item'"
)

ACTIVE_EPIC_TASK_INDEX_DDL = (
    "CREATE UNIQUE INDEX IF NOT EXISTS "
    f"{ACTIVE_EPIC_TASK_INDEX_NAME} "
    "ON work_claims(epic_id, task_num) "
    "WHERE released_at IS NULL AND target_kind='epic_task'"
)


def create_work_claim_active_uniques(conn: Any) -> None:
    """Create the active item and epic-task partial unique indexes.

    Idempotent (``IF NOT EXISTS``). Called by ``schema_init.cmd_init``
    after ``create_core_tables`` so fresh schema creation always
    includes these indexes. Pre-existing authoritative DBs already carry
    the same indexes before this helper becomes the permanent owner.
    """
    conn.execute(ACTIVE_ITEM_INDEX_DDL)
    conn.execute(ACTIVE_EPIC_TASK_INDEX_DDL)


__all__ = [
    "create_work_claim_active_uniques",
    "ACTIVE_ITEM_INDEX_NAME",
    "ACTIVE_EPIC_TASK_INDEX_NAME",
    "ACTIVE_ITEM_INDEX_DDL",
    "ACTIVE_EPIC_TASK_INDEX_DDL",
]
