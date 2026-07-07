"""Postgres-native coverage for schema migration helpers."""

from __future__ import annotations

from pathlib import Path

from yoke_core.domain.schema_migrations import _qa_runs_verdict_trigger_exists
from runtime.api.fixtures.file_test_db import connect_test_db, init_test_db


def test_qa_trigger_probe_does_not_need_sqlite_introspection_shims(
    tmp_path: Path,
) -> None:
    with init_test_db(tmp_path) as db_path:
        conn = connect_test_db(db_path)
        try:
            assert _qa_runs_verdict_trigger_exists(conn)
            sqlite_master = conn.execute(
                "SELECT to_regclass('sqlite_master')"
            ).fetchone()[0]
            assert sqlite_master is None
            assert (
                conn.execute(
                    "SELECT to_regprocedure('pragma_table_info(text)')"
                ).fetchone()[0]
                is None
            )
        finally:
            conn.close()
