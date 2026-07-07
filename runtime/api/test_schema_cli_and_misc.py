"""Pytest coverage for ``yoke_core.domain.schema`` — CLI dispatch,
item_sections, and deleted-migration guards.

DB-touching tests route through the
:mod:`runtime.api.fixtures.file_test_db` seam so the bodies run on the active
Postgres authority.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from yoke_core.domain import db_backend, schema
from yoke_core.domain.schema_common import _get_columns, _get_tables
from runtime.api.fixtures.file_test_db import connect_test_db, init_test_db


def _connect(db_path: str):
    """Backend-aware read connection to a :func:`init_test_db` database.

    Must be called inside the ``with init_test_db(...)`` block so the Postgres
    DSN repoint is still active.
    """
    return connect_test_db(db_path)


def _table_names(conn) -> set[str]:
    return set(_get_tables(conn))


def _column_names(conn, table: str) -> list[str]:
    return _get_columns(conn, table)


class TestCLIMain:
    """main() dispatches subcommands and returns correct exit codes."""

    def test_init_via_main(self, tmp_path: Path) -> None:
        # cmd_init runs at context entry; this asserts main(["init"]) is a
        # working dispatch path by re-running it inside the context (no-op on
        # an already-initialized DB) and reading back the canonical table set.
        def _init_via_main() -> None:
            schema.main(["init"])

        with init_test_db(tmp_path, apply_schema=_init_via_main) as db_path:
            conn = _connect(db_path)
            tables = _table_names(conn)
            conn.close()
        assert "items" in tables

    def test_no_args_exits_2(self) -> None:
        with pytest.raises(SystemExit) as exc_info:
            schema.main([])
        assert exc_info.value.code == 2

    def test_unknown_subcommand_exits_2(self) -> None:
        with pytest.raises(SystemExit) as exc_info:
            schema.main(["nonexistent-subcommand"])
        assert exc_info.value.code == 2

    def test_backfill_source_is_retired(self) -> None:
        with pytest.raises(SystemExit) as exc_info:
            schema.main(["backfill-source"])
        assert exc_info.value.code == 2


class TestItemSections:
    """item_sections table is created with correct schema."""

    def test_item_sections_primary_key(self, tmp_path: Path) -> None:
        """item_sections uses composite PK (item_id, section_name)."""
        with init_test_db(tmp_path) as db_path:
            conn = _connect(db_path)
            # Insert two sections for same item
            conn.execute(
                "INSERT INTO item_sections (item_id, section_name, content, created_at, updated_at) "
                "VALUES (1, 'spec', 'spec content', '2026-01-01T00:00:00Z', '2026-01-01T00:00:00Z')"
            )
            conn.execute(
                "INSERT INTO item_sections (item_id, section_name, content, created_at, updated_at) "
                "VALUES (1, 'design', 'design content', '2026-01-01T00:00:00Z', '2026-01-01T00:00:00Z')"
            )
            conn.commit()

            # Duplicate should fail
            with pytest.raises(db_backend.integrity_error_types()):
                conn.execute(
                    "INSERT INTO item_sections (item_id, section_name, content, created_at, updated_at) "
                    "VALUES (1, 'spec', 'duplicate', '2026-01-01T00:00:00Z', '2026-01-01T00:00:00Z')"
                )
            conn.close()

    def test_item_sections_columns(self, tmp_path: Path) -> None:
        with init_test_db(tmp_path) as db_path:
            conn = _connect(db_path)
            cols = _column_names(conn, "item_sections")
            conn.close()
        for col in ("item_id", "section_name", "content", "ordering", "source",
                     "created_at", "updated_at"):
            assert col in cols, f"item_sections missing column: {col}"


class TestDeletedMigrationCommands:
    """Retired migration helpers must not reappear in the schema module."""

    DELETED_COMMANDS = [
        "cmd_migrate_check_constraints",
        "cmd_migrate_drop_items_epic",
        "cmd_migrate_add_resolution",
        "cmd_migrate_events_correlation",
        "cmd_migrate_events_backfill",
        "cmd_backfill_source",
    ]

    def test_schema_has_no_deleted_migration_commands(self) -> None:
        for name in self.DELETED_COMMANDS:
            assert not hasattr(schema, name), (
                f"Deleted migration '{name}' still present in schema module"
            )
