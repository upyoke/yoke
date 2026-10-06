"""``schema.cmd_init`` is idempotent: a second init neither fails nor loses data.

Each test runs inside :func:`init_test_db`, which has already repointed
``YOKE_PG_DSN`` at a disposable per-test database, so a bare
``schema.cmd_init`` re-applies the schema to that same database.
"""

from __future__ import annotations

from pathlib import Path

from yoke_core.domain import schema
from yoke_core.domain.schema_common import _get_tables
from runtime.api.fixtures.file_test_db import connect_test_db, init_test_db


class TestInitIdempotent:
    """Calling cmd_init twice does not fail or lose data."""

    def test_double_init_no_error(self, tmp_path: Path) -> None:
        with init_test_db(tmp_path):
            # First init ran at context entry; second call should succeed.
            schema.cmd_init()

    def test_double_init_preserves_data(self, tmp_path: Path) -> None:
        with init_test_db(tmp_path) as db_path:
            conn = connect_test_db(db_path)
            conn.execute(
                "INSERT INTO items "
                "(id, title, status, priority, project_id, project_sequence, "
                "workflow_id, workflow_version_id, created_at, updated_at) "
                "VALUES (42, 'preserved', 'idea', 'medium', 1, 42, 'issue', "
                "(SELECT current_version_id FROM workflows WHERE id = 'issue'), "
                "'2025-01-01', '2025-01-01')"
            )
            conn.commit()
            conn.close()

            schema.cmd_init()

            conn = connect_test_db(db_path)
            row = conn.execute("SELECT title FROM items WHERE id=42").fetchone()
            assert row is not None
            assert row[0] == "preserved"
            conn.close()

    def test_double_init_preserves_table_count(self, tmp_path: Path) -> None:
        with init_test_db(tmp_path) as db_path:
            conn = connect_test_db(db_path)
            tables_first = set(_get_tables(conn))
            conn.close()

            schema.cmd_init()

            conn = connect_test_db(db_path)
            tables_second = set(_get_tables(conn))
            conn.close()
            assert tables_first == tables_second
