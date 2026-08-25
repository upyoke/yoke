"""Give strategy-document claims a typed owner and retire the item-only column.

A strategy document could be held only by a work item, so the holder was
one column: the item. A coordinator working the document without an item
had nowhere to record that they held it, and a Blitz created from that
document could be claimed out from under them.

The holder is now ``owner_kind`` plus the one matching owner column —
``owner_item_id`` for a Blitz executing the document, ``owner_session_id``
for a session holding it directly. ``registered_by_*`` stays provenance,
so an item-owned claim still survives the session that registered it.

Every existing row is item-owned, so the backfill is a copy: the item that
held the document keeps holding it. The old column is dropped in the same
entry because nothing reads both shapes — a second owner column that no
reader consults could only drift out of step with the one that decides.
"""

from __future__ import annotations

from typing import Any

from yoke_core.domain import db_backend
from yoke_core.domain.migration_serving_version import NEXT_RELEASE
from yoke_core.domain.schema_common import (
    _add_column_if_not_exists,
    _column_exists,
    _get_check_constraint_defs,
    _table_exists,
)
from yoke_core.domain.strategy_execution_schema import TYPED_OWNER_COLUMNS


#: A build without this entry reads the retired column and cannot serve a
#: database this entry has reached. The sentinel resolves at apply time to
#: the artifact doing the applying, which by construction carries the entry.
MINIMUM_SERVING_VERSION = NEXT_RELEASE

TABLE = "strategy_doc_claims"
RETIRED_COLUMN = "owning_item_id"
OWNER_SHAPE_CONSTRAINT = "strategy_doc_claims_owner_shape_check"
OWNER_SHAPE_SQL = (
    "(owner_kind = 'item' "
    "AND owner_item_id IS NOT NULL AND owner_session_id IS NULL) "
    "OR (owner_kind = 'session' "
    "AND owner_session_id IS NOT NULL AND owner_item_id IS NULL)"
)


def apply(conn: Any) -> None:
    if not _table_exists(conn, TABLE):
        return
    for column, ddl in TYPED_OWNER_COLUMNS:
        _add_column_if_not_exists(conn, TABLE, column, ddl)
    if _column_exists(conn, TABLE, RETIRED_COLUMN):
        conn.execute(
            f"UPDATE {TABLE} SET owner_kind = 'item', "
            f"owner_item_id = {RETIRED_COLUMN} "
            "WHERE owner_item_id IS NULL AND owner_session_id IS NULL "
            f"AND {RETIRED_COLUMN} IS NOT NULL"
        )
        _require_typed_owners(conn)
        _move_owner_indexes(conn)
        conn.execute(f'ALTER TABLE {TABLE} DROP COLUMN "{RETIRED_COLUMN}"')
    _require_typed_owners(conn)
    _ensure_owner_shape_constraint(conn)


def _move_owner_indexes(conn: Any) -> None:
    """Point the owner indexes at the typed column before the drop."""
    conn.execute("DROP INDEX IF EXISTS uq_strategy_doc_claims_active_item")
    conn.execute("DROP INDEX IF EXISTS idx_strategy_doc_claims_item_history")
    conn.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS "
        "uq_strategy_doc_claims_active_owner_item "
        f"ON {TABLE}(owner_item_id) WHERE released_at IS NULL"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_strategy_doc_claims_item_history "
        f"ON {TABLE}(owner_item_id, registered_at)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_strategy_doc_claims_owner_session "
        f"ON {TABLE}(owner_session_id) WHERE released_at IS NULL"
    )


def _require_typed_owners(conn: Any) -> None:
    """Refuse to retire the old column while any row would lose its holder."""
    row = conn.execute(
        f"SELECT COUNT(*) FROM {TABLE} "
        "WHERE owner_item_id IS NULL AND owner_session_id IS NULL"
    ).fetchone()
    untyped = int(row[0] if row is not None else 0)
    if untyped:
        raise AssertionError(
            f"{untyped} {TABLE} row(s) carry no owner; the retired column "
            "cannot be dropped without losing their holder"
        )


def _ensure_owner_shape_constraint(conn: Any) -> None:
    """Add the owner-shape CHECK where the engine can alter constraints."""
    if not db_backend.connection_is_postgres(conn):
        return
    if _owner_shape_constraint_present(conn):
        return
    conn.execute(
        f"ALTER TABLE {TABLE} ADD CONSTRAINT {OWNER_SHAPE_CONSTRAINT} "
        f"CHECK({OWNER_SHAPE_SQL})"
    )


def _owner_shape_constraint_present(conn: Any) -> bool:
    return any(
        "owner_kind" in definition.lower()
        and "owner_session_id" in definition.lower()
        and "owner_item_id" in definition.lower()
        for definition in _get_check_constraint_defs(conn, TABLE)
    )


def invariants(conn: Any) -> None:
    if not _table_exists(conn, TABLE):
        return
    assert not _column_exists(conn, TABLE, RETIRED_COLUMN), (
        f"{TABLE}.{RETIRED_COLUMN} is retired but still present"
    )
    for column, _ddl in TYPED_OWNER_COLUMNS:
        assert _column_exists(conn, TABLE, column), (
            f"{TABLE}.{column} is required but absent"
        )
    _require_typed_owners(conn)
    if db_backend.connection_is_postgres(conn):
        assert _owner_shape_constraint_present(conn), (
            f"{TABLE} must constrain each owner kind to its own owner column"
        )


__all__ = [
    "MINIMUM_SERVING_VERSION",
    "OWNER_SHAPE_CONSTRAINT",
    "RETIRED_COLUMN",
    "TABLE",
    "apply",
    "invariants",
]
