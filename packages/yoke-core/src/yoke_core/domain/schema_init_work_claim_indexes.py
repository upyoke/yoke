"""Partial indexes enforcing active work-claim exclusivity by JSON scope."""

from __future__ import annotations

from typing import Any

from yoke_core.domain.work_claim_targets import scope_text_sql

ACTIVE_ITEM_INDEX_NAME = "idx_work_claims_active_item"
ACTIVE_EPIC_TASK_INDEX_NAME = "idx_work_claims_active_epic_task"
ACTIVE_PROCESS_CONFLICT_INDEX_NAME = "idx_work_claims_active_process_conflict"
ACTIVE_STEERING_INDEX_NAME = "idx_work_claims_active_steering"

ACTIVE_ITEM_INDEX_DDL = (
    "CREATE UNIQUE INDEX IF NOT EXISTS "
    f"{ACTIVE_ITEM_INDEX_NAME} ON work_claims(scope) "
    "WHERE released_at IS NULL AND target_kind='item'"
)

ACTIVE_EPIC_TASK_INDEX_DDL = (
    "CREATE UNIQUE INDEX IF NOT EXISTS "
    f"{ACTIVE_EPIC_TASK_INDEX_NAME} ON work_claims(scope) "
    "WHERE released_at IS NULL AND target_kind='epic_task'"
)

ACTIVE_STEERING_INDEX_DDL = (
    "CREATE UNIQUE INDEX IF NOT EXISTS "
    f"{ACTIVE_STEERING_INDEX_NAME} ON work_claims(scope) "
    "WHERE released_at IS NULL AND target_kind='steering'"
)


def active_process_conflict_index_ddl(conn: Any) -> str:
    """Build the backend-specific conflict-group expression index."""
    conflict_group = scope_text_sql(conn, "scope", "conflict_group")
    return (
        "CREATE UNIQUE INDEX IF NOT EXISTS "
        f"{ACTIVE_PROCESS_CONFLICT_INDEX_NAME} "
        f"ON work_claims(({conflict_group})) "
        "WHERE released_at IS NULL AND target_kind='process'"
    )


def create_work_claim_active_uniques(conn: Any) -> None:
    """Create every active-target exclusivity index idempotently."""
    conn.execute(ACTIVE_ITEM_INDEX_DDL)
    conn.execute(ACTIVE_EPIC_TASK_INDEX_DDL)
    conn.execute(active_process_conflict_index_ddl(conn))
    conn.execute(ACTIVE_STEERING_INDEX_DDL)


__all__ = [
    "ACTIVE_EPIC_TASK_INDEX_DDL",
    "ACTIVE_EPIC_TASK_INDEX_NAME",
    "ACTIVE_ITEM_INDEX_DDL",
    "ACTIVE_ITEM_INDEX_NAME",
    "ACTIVE_PROCESS_CONFLICT_INDEX_NAME",
    "ACTIVE_STEERING_INDEX_DDL",
    "ACTIVE_STEERING_INDEX_NAME",
    "active_process_conflict_index_ddl",
    "create_work_claim_active_uniques",
]
