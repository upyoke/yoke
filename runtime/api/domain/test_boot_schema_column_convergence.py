"""Column parity between fresh and boot-converged control-plane schemas.

``CREATE TABLE IF NOT EXISTS`` leaves an existing table untouched. A column
added only to a table's create statement therefore reaches fresh databases but
not databases that already hold the table. This degradation sweep removes each
column PostgreSQL can drop without an explicit ``CASCADE`` and proves that the
real boot converge restores the complete fresh column map.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

from psycopg import Error, sql

from runtime.api.fixtures.file_test_db import connect_test_db, init_test_db
from yoke_core.domain import deployment_runs_schema, schema, schema_common_postgres
from yoke_core.domain.schema_common import _get_columns, _get_tables
from yoke_core.domain.schema_init import converge_core_schema


_DROP_SAVEPOINT = "boot_schema_column_degradation"
_INCIDENT_COLUMN = ("session_launch_attempts", "batch_id")
# Columns delivered by ordered history with a data or key transformation are
# current baseline columns on a newborn database, but intentionally have no
# additive lookup. Their migration suites prove convergence from the prior
# shape; this sweep must neither classify them as born-with nor drop them after
# their ledger entry has already been recorded.
_HISTORY_CONVERGED_COLUMNS = frozenset(
    {("test_machine_verifications", "capability_type")}
)
# Digest of columns that shipped with their table and therefore have no
# additive converge lookup. Update only when introducing a new table, or when
# a governed migration retires a born-with column; a new column on an existing
# table must instead restore through boot convergence and leave this digest
# unchanged.
_BORN_WITH_COLUMN_DIGEST = (
    "847b2aa4db85e9aa97bf351bcbf93d8176b9f33aefaab004326cb3281e4fa6c8"
)


def _apply_complete_control_plane_schema() -> None:
    schema.cmd_init()
    deployment_runs_schema.cmd_init()


def _column_map(conn) -> dict[str, frozenset[str]]:
    return {table: frozenset(_get_columns(conn, table)) for table in _get_tables(conn)}


def _record_boot_column_lookups(conn, monkeypatch) -> set[tuple[str, str]]:
    columns: set[tuple[str, str]] = set()
    original = schema_common_postgres._postgres_column_row

    def record(connection, table: str, column: str):
        columns.add((table, column))
        return original(connection, table, column)

    with monkeypatch.context() as patcher:
        patcher.setattr(schema_common_postgres, "_postgres_column_row", record)
        converge_core_schema(conn)
    return columns


def _drop_without_cascade(conn, table: str, column: str) -> bool:
    """Drop one independent column, or report a dependency-protected skip."""
    conn.execute(sql.SQL("SAVEPOINT {}").format(sql.Identifier(_DROP_SAVEPOINT)))
    try:
        conn.execute(
            sql.SQL("ALTER TABLE {} DROP COLUMN {}").format(
                sql.Identifier(table),
                sql.Identifier(column),
            )
        )
    except Error:
        conn.execute(
            sql.SQL("ROLLBACK TO SAVEPOINT {}").format(sql.Identifier(_DROP_SAVEPOINT))
        )
        conn.execute(
            sql.SQL("RELEASE SAVEPOINT {}").format(sql.Identifier(_DROP_SAVEPOINT))
        )
        conn.commit()
        return False
    conn.execute(
        sql.SQL("RELEASE SAVEPOINT {}").format(sql.Identifier(_DROP_SAVEPOINT))
    )
    conn.commit()
    return True


def _column_pair_digest(columns: set[tuple[str, str]]) -> str:
    payload = "\n".join(f"{table}.{column}" for table, column in sorted(columns))
    return hashlib.sha256(payload.encode()).hexdigest()


def test_every_droppable_boot_schema_column_converges(
    tmp_path: Path,
    monkeypatch,
) -> None:
    with init_test_db(
        tmp_path,
        apply_schema=_apply_complete_control_plane_schema,
    ) as db_path:
        conn = connect_test_db(db_path)
        try:
            fresh_columns = _column_map(conn)
            all_columns = {
                (table, column)
                for table, columns in fresh_columns.items()
                for column in columns
            }
            boot_lookups = _record_boot_column_lookups(conn, monkeypatch)

            assert _HISTORY_CONVERGED_COLUMNS <= all_columns, (
                "history-managed columns are absent from the current baseline: "
                f"{sorted(_HISTORY_CONVERGED_COLUMNS - all_columns)}"
            )
            assert _HISTORY_CONVERGED_COLUMNS.isdisjoint(boot_lookups), (
                "history-managed columns also have an additive converge path: "
                f"{sorted(_HISTORY_CONVERGED_COLUMNS & boot_lookups)}"
            )
            born_with = all_columns - boot_lookups - _HISTORY_CONVERGED_COLUMNS
            born_with_digest = _column_pair_digest(born_with)
            assert born_with_digest == _BORN_WITH_COLUMN_DIGEST, (
                "create-only columns changed; add boot convergence for columns on "
                "existing tables or justify a newly introduced table; "
                f"digest={born_with_digest}: {sorted(born_with)}"
            )

            expected_additive = all_columns & boot_lookups
            dropped = {
                pair
                for pair in sorted(expected_additive)
                if _drop_without_cascade(conn, *pair)
            }
            assert dropped, "the degradation sweep did not exercise any columns"
            assert _INCIDENT_COLUMN in dropped

            converge_core_schema(conn)

            assert _column_map(conn) == fresh_columns, (
                "boot converge did not restore the fresh column map after dropping "
                f"additive candidates: {sorted(dropped)}"
            )
        finally:
            conn.close()
