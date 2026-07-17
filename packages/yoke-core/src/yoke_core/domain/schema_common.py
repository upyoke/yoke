"""Shared schema CLI/helper functions.

Active Yoke authority is Postgres. Native readers below use Postgres catalogs
directly; the ``generic_sqlite_validation`` helpers are only for external
sqlite_file / worktree-local SQLite validation surfaces, never for the Yoke
control plane.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, List, Optional, Tuple

from yoke_core.domain.schema_common_postgres import (
    _postgres_check_constraint_defs,
    _postgres_column_exists,
    _postgres_column_is_not_null,
    _postgres_get_column_default,
    _postgres_get_columns,
    _postgres_get_columns_with_types,
    _postgres_get_indexes,
    _postgres_get_tables,
    _postgres_table_exists,
)
from yoke_core.domain.schema_common_sqlite_validation import (
    _generic_sqlite_validation_check_constraint_defs,
    _generic_sqlite_validation_column_exists,
    _generic_sqlite_validation_column_is_not_null,
    _generic_sqlite_validation_get_column_default,
    _generic_sqlite_validation_get_columns,
    _generic_sqlite_validation_get_columns_with_types,
    _generic_sqlite_validation_get_indexes,
    _generic_sqlite_validation_get_tables,
    _generic_sqlite_validation_table_create_sql,
    _generic_sqlite_validation_table_exists,
    _generic_sqlite_validation_table_info,
)
from yoke_core.domain.schema_orphans import (
    _check_sibling_state_collision,
    check_sibling_state_collision,
    guard_state_dir_creation,
)

_USAGE = """\
Usage: python3 -m yoke_core.domain.schema <subcmd>

Subcommands:
  init                            Create DB and shared tables (idempotent)
  migration-audit-list            List recent migration audit records
  migration-verify                Verify DB state against last migration baseline"""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _cli_error(msg: str, code: int = 1) -> None:
    print(f"Error: {msg}", file=sys.stderr)
    sys.exit(code)


def _cli_usage_error(msg: str) -> None:
    print(msg, file=sys.stderr)
    sys.exit(2)


def _resolve_db_path() -> str:
    """Resolve the retired SQLite DB path for legacy commands.

    Active schema work is Postgres-only and should call :func:`_connect_raw`
    without using this path. The path remains for legacy migration-audit CLI
    surfaces that have not yet been deleted.
    """
    from yoke_core.domain import db_backend

    if db_backend.is_postgres():
        return ""
    try:
        from yoke_core.domain.db_helpers import resolve_db_path

        return resolve_db_path()
    except (FileNotFoundError, ImportError):
        from yoke_core.domain.worktree import resolve_db_path as resolve_worktree_db_path

        return resolve_worktree_db_path()


def _resolve_db_root() -> str:
    """Return the directory that contains legacy ``yoke.db``."""
    if not _resolve_db_path():
        return ""
    return str(Path(_resolve_db_path()).parent)


def _connect_raw(db_path: str = "") -> Any:
    """Open the active Postgres authority connection."""
    from yoke_core.domain import db_backend

    return db_backend.connect(db_path)


def _connection_is_postgres(conn: Any) -> bool:
    from yoke_core.domain import db_backend

    return db_backend.connection_is_postgres(conn)


def _using_generic_sqlite_validation(conn: Any) -> bool:
    """Return whether *conn* is the non-authority generic SQLite boundary."""
    return not _connection_is_postgres(conn)


def _table_exists(conn: Any, table: str) -> bool:
    if _using_generic_sqlite_validation(conn):
        return _generic_sqlite_validation_table_exists(conn, table)
    return _postgres_table_exists(conn, table)


def _table_create_sql(conn: Any, table: str) -> Optional[str]:
    """Return SQLite CREATE text when the generic validation DB stores it."""
    if _using_generic_sqlite_validation(conn):
        return _generic_sqlite_validation_table_create_sql(conn, table)
    return None


def _get_tables(conn: Any) -> List[str]:
    """Return the user/base table names, ordered by name."""
    if _using_generic_sqlite_validation(conn):
        return _generic_sqlite_validation_get_tables(conn)
    return _postgres_get_tables(conn)


def _column_exists(conn: Any, table: str, column: str) -> bool:
    if _using_generic_sqlite_validation(conn):
        return _generic_sqlite_validation_column_exists(conn, table, column)
    return _postgres_column_exists(conn, table, column)


def _column_is_not_null(conn: Any, table: str, column: str) -> bool:
    """Return whether ``table.column`` carries a NOT NULL constraint."""
    if _using_generic_sqlite_validation(conn):
        return _generic_sqlite_validation_column_is_not_null(conn, table, column)
    return _postgres_column_is_not_null(conn, table, column)


def _get_columns(conn: Any, table: str) -> List[str]:
    if _using_generic_sqlite_validation(conn):
        return _generic_sqlite_validation_get_columns(conn, table)
    return _postgres_get_columns(conn, table)


def _get_columns_with_types(conn: Any, table: str) -> List[Tuple[str, str]]:
    if _using_generic_sqlite_validation(conn):
        return _generic_sqlite_validation_get_columns_with_types(conn, table)
    return _postgres_get_columns_with_types(conn, table)


def _get_column_default(conn: Any, table: str, column: str) -> Optional[str]:
    if _using_generic_sqlite_validation(conn):
        return _generic_sqlite_validation_get_column_default(conn, table, column)
    return _postgres_get_column_default(conn, table, column)


def _get_indexes(conn: Any, table: Optional[str] = None) -> List[str]:
    if _using_generic_sqlite_validation(conn):
        return _generic_sqlite_validation_get_indexes(conn, table)
    return _postgres_get_indexes(conn, table)


def _index_exists(conn: Any, index: str, table: Optional[str] = None) -> bool:
    return index in set(_get_indexes(conn, table))


def _get_check_constraint_defs(conn: Any, table: str) -> List[str]:
    if _using_generic_sqlite_validation(conn):
        return _generic_sqlite_validation_check_constraint_defs(conn, table)
    return _postgres_check_constraint_defs(conn, table)


def _add_column_if_not_exists(
    conn: Any, table: str, column: str, col_def: str
) -> None:
    """Idempotent ADD COLUMN."""
    if not _column_exists(conn, table, column):
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {col_def}")
