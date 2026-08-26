"""Cut work claims over from specialized columns to one JSON scope."""

from __future__ import annotations

from typing import Any

from yoke_core.domain import db_backend
from yoke_core.domain.migration_serving_version import NEXT_RELEASE
from yoke_core.domain.schema_common import (
    _column_exists,
    _get_check_constraint_defs,
    _get_indexes,
    _table_exists,
)
from yoke_core.domain.schema_init_columns import apply_work_claim_scope_column
from yoke_core.domain.schema_init_work_claim_indexes import (
    ACTIVE_EPIC_TASK_INDEX_NAME,
    ACTIVE_ITEM_INDEX_NAME,
    ACTIVE_PROCESS_CONFLICT_INDEX_NAME,
    ACTIVE_STEERING_INDEX_NAME,
    create_work_claim_active_uniques,
)
from yoke_core.domain.work_claim_targets import (
    TARGET_KIND_EPIC_TASK,
    TARGET_KIND_ITEM,
    TARGET_KIND_PROCESS,
    TARGET_KIND_STEERING,
    WorkClaimTarget,
    decode_scope,
    encode_scope,
)

MINIMUM_SERVING_VERSION = NEXT_RELEASE
TABLE = "work_claims"
SCOPE_COLUMN = "scope"

LEGACY_TARGET_COLUMNS = (
    "item_id",
    "epic_id",
    "task_num",
    "process_key",
    "conflict_group",
)
UNSHIPPED_COLUMNS = (
    "steering_project_id",
    "steering_strategy_doc_slugs",
    "owner_kind",
    "owner_item_id",
    "owner_session_id",
    "owner_work_claim_id",
    "registered_by_actor_id",
    "registered_by_session_id",
)
RETIRED_COLUMNS = LEGACY_TARGET_COLUMNS + UNSHIPPED_COLUMNS

TARGET_KIND_CONSTRAINT = "work_claims_target_kind_check"
TARGET_KIND_SQL = "target_kind IN ('item','epic_task','process','steering')"

_RETIRED_INDEXES = (
    "idx_work_claims_item",
    "idx_work_claims_epic_task",
    "idx_work_claims_process",
    "idx_work_claims_active_item",
    "idx_work_claims_active_epic_task",
    "idx_work_claims_active_process_conflict",
    "idx_work_claims_active_steering_scope_identity",
    "idx_work_claims_steering_project_active",
    "idx_work_claims_owner_session",
    "idx_work_claims_registered_by_actor",
)


def _p(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def _selected_columns(conn: Any) -> list[str]:
    columns = ["id", "target_kind", SCOPE_COLUMN]
    columns.extend(
        column for column in RETIRED_COLUMNS if _column_exists(conn, TABLE, column)
    )
    return columns


def _mapping(row: Any, columns: list[str]) -> dict[str, Any]:
    if hasattr(row, "keys"):
        return dict(row)
    return dict(zip(columns, row))


def _scope_from_legacy(row: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    kind = str(row["target_kind"])
    if kind == TARGET_KIND_ITEM:
        return kind, {"item_id": int(row["item_id"])}
    if kind == TARGET_KIND_EPIC_TASK:
        return kind, {
            "epic_id": int(row["epic_id"]),
            "task_num": int(row["task_num"]),
        }
    if kind == TARGET_KIND_PROCESS:
        return kind, {
            "process_key": str(row["process_key"]),
            "conflict_group": str(row["conflict_group"]),
        }
    if kind in {"steering_scope", TARGET_KIND_STEERING}:
        project_id = row.get("steering_project_id")
        if project_id is None:
            existing = decode_scope(row.get(SCOPE_COLUMN))
            project_id = existing.get("project_id")
        return TARGET_KIND_STEERING, {"project_id": int(project_id)}
    raise AssertionError(f"unsupported work_claims target_kind {kind!r}")


def _backfill_scope(conn: Any) -> None:
    columns = _selected_columns(conn)
    rows = conn.execute(
        f"SELECT {', '.join(columns)} FROM {TABLE} ORDER BY id"
    ).fetchall()
    p = _p(conn)
    for raw in rows:
        row = _mapping(raw, columns)
        kind = str(row["target_kind"])
        stored_scope = row.get(SCOPE_COLUMN)
        if stored_scope is not None and kind != "steering_scope":
            target = WorkClaimTarget(kind, decode_scope(stored_scope))
            normalized_kind = target.kind
            normalized_scope = target.scope_json()
        else:
            normalized_kind, scope = _scope_from_legacy(row)
            normalized_scope = encode_scope(scope)
            WorkClaimTarget(normalized_kind, scope)
        conn.execute(
            f"UPDATE {TABLE} SET target_kind = {p}, scope = {p} WHERE id = {p}",
            (normalized_kind, normalized_scope, int(row["id"])),
        )


def _drop_postgres_checks(conn: Any) -> None:
    rows = conn.execute(
        "SELECT con.conname, pg_get_constraintdef(con.oid) "
        "FROM pg_constraint con "
        "JOIN pg_class rel ON rel.oid=con.conrelid "
        "JOIN pg_namespace ns ON ns.oid=rel.relnamespace "
        "WHERE ns.nspname=current_schema() AND rel.relname=%s "
        "AND con.contype='c'",
        (TABLE,),
    ).fetchall()
    for name, definition in rows:
        lowered = str(definition).lower()
        if "target_kind" not in lowered and not any(
            column in lowered for column in RETIRED_COLUMNS
        ):
            continue
        escaped = str(name).replace('"', '""')
        conn.execute(f'ALTER TABLE "{TABLE}" DROP CONSTRAINT "{escaped}"')


def _drop_retired_indexes(conn: Any) -> None:
    existing = set(_get_indexes(conn, TABLE))
    for name in _RETIRED_INDEXES:
        if name in existing:
            escaped = name.replace('"', '""')
            conn.execute(f'DROP INDEX IF EXISTS "{escaped}"')


def _drop_retired_columns(conn: Any) -> None:
    for column in RETIRED_COLUMNS:
        if _column_exists(conn, TABLE, column):
            conn.execute(f'ALTER TABLE "{TABLE}" DROP COLUMN "{column}"')


def _install_final_constraints(conn: Any) -> None:
    if db_backend.connection_is_postgres(conn):
        conn.execute(f"ALTER TABLE {TABLE} ALTER COLUMN scope SET NOT NULL")
    conn.execute(
        f"ALTER TABLE {TABLE} ADD CONSTRAINT {TARGET_KIND_CONSTRAINT} "
        f"CHECK({TARGET_KIND_SQL})"
    )


def apply(conn: Any) -> None:
    if not _table_exists(conn, TABLE):
        return
    if not _column_exists(conn, TABLE, SCOPE_COLUMN):
        apply_work_claim_scope_column(conn)
    before = int(conn.execute(f"SELECT COUNT(*) FROM {TABLE}").fetchone()[0])
    _backfill_scope(conn)
    if db_backend.connection_is_postgres(conn):
        _drop_postgres_checks(conn)
    _drop_retired_indexes(conn)
    _drop_retired_columns(conn)
    _install_final_constraints(conn)
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_work_claims_scope ON work_claims(scope)"
    )
    create_work_claim_active_uniques(conn)
    after = int(conn.execute(f"SELECT COUNT(*) FROM {TABLE}").fetchone()[0])
    if after != before:
        raise AssertionError(
            f"{TABLE} row count changed during scope cutover: {before} -> {after}"
        )


def invariants(conn: Any) -> None:
    if not _table_exists(conn, TABLE):
        return
    assert _column_exists(conn, TABLE, SCOPE_COLUMN)
    for column in RETIRED_COLUMNS:
        assert not _column_exists(conn, TABLE, column), (
            f"{TABLE}.{column} must be retired"
        )
    rows = conn.execute(
        f"SELECT target_kind, scope FROM {TABLE} ORDER BY id"
    ).fetchall()
    for row in rows:
        target_kind = row["target_kind"] if hasattr(row, "keys") else row[0]
        scope = row["scope"] if hasattr(row, "keys") else row[1]
        WorkClaimTarget(str(target_kind), decode_scope(scope))
    if db_backend.connection_is_postgres(conn):
        checks = " ".join(_get_check_constraint_defs(conn, TABLE)).lower()
        assert "target_kind" in checks and "steering" in checks
    indexes = set(_get_indexes(conn, TABLE))
    for name in (
        ACTIVE_ITEM_INDEX_NAME,
        ACTIVE_EPIC_TASK_INDEX_NAME,
        ACTIVE_PROCESS_CONFLICT_INDEX_NAME,
        ACTIVE_STEERING_INDEX_NAME,
    ):
        assert name in indexes, f"{TABLE} is missing index {name}"


__all__ = [
    "LEGACY_TARGET_COLUMNS",
    "MINIMUM_SERVING_VERSION",
    "RETIRED_COLUMNS",
    "SCOPE_COLUMN",
    "TABLE",
    "TARGET_KIND_CONSTRAINT",
    "TARGET_KIND_SQL",
    "UNSHIPPED_COLUMNS",
    "apply",
    "invariants",
]
