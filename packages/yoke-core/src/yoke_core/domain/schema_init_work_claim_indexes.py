"""Partial indexes enforcing active work-claim exclusivity by JSON scope."""

from __future__ import annotations

from typing import Any

from yoke_core.domain.work_claim_targets import scope_text_sql

ACTIVE_ITEM_INDEX_NAME = "idx_work_claims_active_item"
ACTIVE_EPIC_TASK_INDEX_NAME = "idx_work_claims_active_epic_task"
ACTIVE_PROCESS_CONFLICT_INDEX_NAME = "idx_work_claims_active_process_conflict"
ACTIVE_STEERING_INDEX_NAME = "idx_work_claims_active_steering"
ACTIVE_QA_ADMISSION_INDEX_NAME = "idx_work_claims_active_qa_admission"
ACTIVE_ROUTE_QUALIFICATION_INDEX_NAME = "idx_work_claims_active_route_qualification"
ACTIVE_MIGRATION_SERIALIZATION_INDEX_NAME = (
    "idx_work_claims_active_migration_serialization"
)

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


ACTIVE_QA_ADMISSION_INDEX_DDL = (
    "CREATE UNIQUE INDEX IF NOT EXISTS "
    f"{ACTIVE_QA_ADMISSION_INDEX_NAME} ON work_claims(scope) "
    "WHERE released_at IS NULL AND target_kind='qa_admission'"
)

ACTIVE_ROUTE_QUALIFICATION_INDEX_DDL = (
    "CREATE UNIQUE INDEX IF NOT EXISTS "
    f"{ACTIVE_ROUTE_QUALIFICATION_INDEX_NAME} ON work_claims(scope) "
    "WHERE released_at IS NULL AND target_kind='route_qualification'"
)


def active_migration_serialization_index_ddl(conn: Any) -> str:
    """Build the per-model migration-territory exclusivity index.

    The owning item rides in the scope but is not part of the unit: one
    model in one project admits one live claim whichever item holds it.
    """
    project = scope_text_sql(conn, "scope", "project_id")
    model = scope_text_sql(conn, "scope", "model")
    return (
        "CREATE UNIQUE INDEX IF NOT EXISTS "
        f"{ACTIVE_MIGRATION_SERIALIZATION_INDEX_NAME} "
        f"ON work_claims(({project}), ({model})) "
        "WHERE released_at IS NULL AND target_kind='migration_serialization'"
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
    conn.execute(ACTIVE_QA_ADMISSION_INDEX_DDL)
    conn.execute(ACTIVE_ROUTE_QUALIFICATION_INDEX_DDL)
    conn.execute(active_migration_serialization_index_ddl(conn))


__all__ = [
    "ACTIVE_EPIC_TASK_INDEX_DDL",
    "ACTIVE_MIGRATION_SERIALIZATION_INDEX_NAME",
    "ACTIVE_QA_ADMISSION_INDEX_DDL",
    "ACTIVE_QA_ADMISSION_INDEX_NAME",
    "ACTIVE_ROUTE_QUALIFICATION_INDEX_DDL",
    "ACTIVE_ROUTE_QUALIFICATION_INDEX_NAME",
    "ACTIVE_EPIC_TASK_INDEX_NAME",
    "ACTIVE_ITEM_INDEX_DDL",
    "ACTIVE_ITEM_INDEX_NAME",
    "ACTIVE_PROCESS_CONFLICT_INDEX_NAME",
    "ACTIVE_STEERING_INDEX_DDL",
    "ACTIVE_STEERING_INDEX_NAME",
    "active_migration_serialization_index_ddl",
    "active_process_conflict_index_ddl",
    "create_work_claim_active_uniques",
]
