"""Add session-owned steering scopes to the typed work-claim authority.

The cutover adds one target kind to ``work_claims``. Existing item, task,
and process rows remain byte-for-byte target-equivalent and acquire NULLs
for the new target and ownership columns. PostgreSQL's target checks are
replaced in the same transaction, so no serving build observes two claim
authorities or a half-supported steering row.
"""

from __future__ import annotations

from typing import Any

from yoke_core.domain import db_backend
from yoke_core.domain.migration_serving_version import NEXT_RELEASE
from yoke_core.domain.schema_common import (
    _add_column_if_not_exists,
    _column_exists,
    _get_check_constraint_defs,
    _get_indexes,
    _table_exists,
)

MINIMUM_SERVING_VERSION = NEXT_RELEASE
TABLE = "work_claims"

COLUMN_DEFS: tuple[tuple[str, str], ...] = (
    ("steering_project_id", "INTEGER DEFAULT NULL"),
    ("steering_strategy_doc_slugs", "TEXT DEFAULT NULL"),
    ("owner_kind", "TEXT DEFAULT NULL"),
    ("owner_item_id", "INTEGER DEFAULT NULL"),
    ("owner_session_id", "TEXT DEFAULT NULL"),
    ("owner_work_claim_id", "INTEGER DEFAULT NULL"),
    ("registered_by_actor_id", "INTEGER DEFAULT NULL"),
    ("registered_by_session_id", "TEXT DEFAULT NULL"),
)

TARGET_KIND_CONSTRAINT = "work_claims_target_kind_check"
TARGET_SHAPE_CONSTRAINT = "work_claims_target_shape_check"
OWNER_SHAPE_CONSTRAINT = "work_claims_owner_shape_check"

TARGET_KIND_SQL = "target_kind IN ('item','epic_task','process','steering_scope')"
TARGET_SHAPE_SQL = " OR ".join(
    (
        "(target_kind='item' AND item_id IS NOT NULL AND epic_id IS NULL "
        "AND task_num IS NULL AND process_key IS NULL AND conflict_group IS NULL "
        "AND steering_project_id IS NULL AND steering_strategy_doc_slugs IS NULL)",
        "(target_kind='epic_task' AND item_id IS NULL AND epic_id IS NOT NULL "
        "AND task_num IS NOT NULL AND process_key IS NULL AND conflict_group IS NULL "
        "AND steering_project_id IS NULL AND steering_strategy_doc_slugs IS NULL)",
        "(target_kind='process' AND item_id IS NULL AND epic_id IS NULL "
        "AND task_num IS NULL AND process_key IS NOT NULL "
        "AND conflict_group IS NOT NULL AND steering_project_id IS NULL "
        "AND steering_strategy_doc_slugs IS NULL)",
        "(target_kind='steering_scope' AND item_id IS NULL AND epic_id IS NULL "
        "AND task_num IS NULL AND process_key IS NULL AND conflict_group IS NULL "
        "AND steering_project_id IS NOT NULL "
        "AND steering_strategy_doc_slugs IS NOT NULL)",
    )
)
OWNER_SHAPE_SQL = " OR ".join(
    (
        "(target_kind<>'steering_scope' AND owner_kind IS NULL "
        "AND owner_item_id IS NULL AND owner_session_id IS NULL "
        "AND owner_work_claim_id IS NULL AND registered_by_actor_id IS NULL "
        "AND registered_by_session_id IS NULL)",
        "(target_kind='steering_scope' AND owner_kind='session' "
        "AND owner_item_id IS NULL AND owner_session_id=session_id "
        "AND owner_work_claim_id IS NULL AND registered_by_actor_id IS NOT NULL "
        "AND registered_by_session_id IS NOT NULL)",
    )
)

INDEX_DDLS = (
    "CREATE UNIQUE INDEX IF NOT EXISTS "
    "idx_work_claims_active_steering_scope_identity "
    "ON work_claims(steering_project_id, steering_strategy_doc_slugs) "
    "WHERE released_at IS NULL AND target_kind='steering_scope'",
    "CREATE INDEX IF NOT EXISTS idx_work_claims_steering_project_active "
    "ON work_claims(steering_project_id) "
    "WHERE released_at IS NULL AND target_kind='steering_scope'",
    "CREATE INDEX IF NOT EXISTS idx_work_claims_owner_session "
    "ON work_claims(owner_session_id) WHERE owner_session_id IS NOT NULL",
    "CREATE INDEX IF NOT EXISTS idx_work_claims_registered_by_actor "
    "ON work_claims(registered_by_actor_id) "
    "WHERE registered_by_actor_id IS NOT NULL",
)


def _replace_postgres_checks(conn: Any) -> None:
    rows = conn.execute(
        "SELECT con.conname FROM pg_constraint con "
        "JOIN pg_class rel ON rel.oid=con.conrelid "
        "JOIN pg_namespace ns ON ns.oid=rel.relnamespace "
        "WHERE ns.nspname=current_schema() AND rel.relname=%s "
        "AND con.contype='c' "
        "AND pg_get_constraintdef(con.oid) ILIKE '%%target_kind%%'",
        (TABLE,),
    ).fetchall()
    for row in rows:
        name = str(row[0]).replace('"', '""')
        conn.execute(f'ALTER TABLE "{TABLE}" DROP CONSTRAINT "{name}"')
    conn.execute(
        f"ALTER TABLE {TABLE} ADD CONSTRAINT {TARGET_KIND_CONSTRAINT} "
        f"CHECK({TARGET_KIND_SQL})"
    )
    conn.execute(
        f"ALTER TABLE {TABLE} ADD CONSTRAINT {TARGET_SHAPE_CONSTRAINT} "
        f"CHECK({TARGET_SHAPE_SQL})"
    )
    conn.execute(
        f"ALTER TABLE {TABLE} ADD CONSTRAINT {OWNER_SHAPE_CONSTRAINT} "
        f"CHECK({OWNER_SHAPE_SQL})"
    )


def apply(conn: Any) -> None:
    if not _table_exists(conn, TABLE):
        return
    before = int(conn.execute(f"SELECT COUNT(*) FROM {TABLE}").fetchone()[0])
    for column, ddl in COLUMN_DEFS:
        _add_column_if_not_exists(conn, TABLE, column, ddl)
    if db_backend.connection_is_postgres(conn):
        _replace_postgres_checks(conn)
    for ddl in INDEX_DDLS:
        conn.execute(ddl)
    after = int(conn.execute(f"SELECT COUNT(*) FROM {TABLE}").fetchone()[0])
    if after != before:
        raise AssertionError(
            f"{TABLE} row count changed during steering-scope cutover: "
            f"{before} -> {after}"
        )


def invariants(conn: Any) -> None:
    if not _table_exists(conn, TABLE):
        return
    for column, _ddl in COLUMN_DEFS:
        assert _column_exists(conn, TABLE, column), f"{TABLE}.{column} is required"
    invalid_legacy = conn.execute(
        f"SELECT COUNT(*) FROM {TABLE} WHERE target_kind <> 'steering_scope' "
        "AND (steering_project_id IS NOT NULL "
        "OR steering_strategy_doc_slugs IS NOT NULL OR owner_kind IS NOT NULL "
        "OR owner_item_id IS NOT NULL OR owner_session_id IS NOT NULL "
        "OR owner_work_claim_id IS NOT NULL OR registered_by_actor_id IS NOT NULL "
        "OR registered_by_session_id IS NOT NULL)"
    ).fetchone()[0]
    assert int(invalid_legacy) == 0, "pre-existing work claims gained steering state"
    invalid_steering = conn.execute(
        f"SELECT COUNT(*) FROM {TABLE} WHERE target_kind = 'steering_scope' "
        "AND (steering_project_id IS NULL OR steering_strategy_doc_slugs IS NULL "
        "OR owner_kind <> 'session' OR owner_session_id <> session_id "
        "OR owner_item_id IS NOT NULL OR owner_work_claim_id IS NOT NULL "
        "OR registered_by_actor_id IS NULL OR registered_by_session_id IS NULL)"
    ).fetchone()[0]
    assert int(invalid_steering) == 0, "steering claims must have one session owner"
    if db_backend.connection_is_postgres(conn):
        checks = " ".join(_get_check_constraint_defs(conn, TABLE)).lower()
        assert "steering_scope" in checks and "owner_session_id" in checks
    indexes = set(_get_indexes(conn, TABLE))
    for name in (
        "idx_work_claims_active_steering_scope_identity",
        "idx_work_claims_steering_project_active",
        "idx_work_claims_owner_session",
        "idx_work_claims_registered_by_actor",
    ):
        assert name in indexes, f"{TABLE} is missing index {name}"


__all__ = [
    "COLUMN_DEFS",
    "MINIMUM_SERVING_VERSION",
    "OWNER_SHAPE_CONSTRAINT",
    "TABLE",
    "TARGET_KIND_CONSTRAINT",
    "TARGET_SHAPE_CONSTRAINT",
    "apply",
    "invariants",
]
