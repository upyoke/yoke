"""The additive converge changes only what is missing, one table at a time."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from pglast import ast, parse_sql

from runtime.api.fixtures.file_test_db import connect_test_db, init_test_db
from yoke_core.domain import db_helpers, schema_converge_statements
from yoke_core.domain import schema_creation
from yoke_core.domain.schema_common import _column_exists
from yoke_core.domain.schema_converge_statements import (
    LOCK_UNAVAILABLE,
    SchemaConvergeLockError,
)

# A DO block decides inside the database whether to change anything; the
# writer-lock test below is what proves a converged run of one locks nothing.
_DATA_STATEMENTS = (
    ast.DoStmt,
    ast.SelectStmt,
    ast.InsertStmt,
    ast.UpdateStmt,
    ast.DeleteStmt,
    ast.VariableSetStmt,
    ast.VariableShowStmt,
)


def _converge_recording(conn: Any, monkeypatch) -> list:
    guards: list = []
    wrap = schema_converge_statements.converging_missing_schema

    def recording(inner):
        context = wrap(inner)
        guard = context.__enter__()
        guards.append(guard)

        class _Recorded:
            def __enter__(self):
                return guard

            def __exit__(self, *exc):
                return context.__exit__(*exc)

        return _Recorded()

    monkeypatch.setattr(schema_creation, "converging_missing_schema", recording)
    schema_creation.converge_additive_schema(conn)
    return guards


def _schema_changes(executed: list[str]) -> list[str]:
    changes = []
    for sql in executed:
        stmt = parse_sql(sql.replace("%s", "$1"))[0].stmt
        if not isinstance(stmt, _DATA_STATEMENTS):
            changes.append(" ".join(sql.split())[:160])
    return changes


@pytest.fixture
def converged(tmp_path: Path):
    with init_test_db(tmp_path) as db_path:
        conn = connect_test_db(db_path)
        try:
            yield conn
        finally:
            conn.close()


def test_converged_schema_issues_no_schema_change(converged, monkeypatch) -> None:
    (guard,) = _converge_recording(converged, monkeypatch)

    assert _schema_changes(guard.executed) == [], "\n".join(
        _schema_changes(guard.executed)
    )
    assert guard.skipped


def test_converged_schema_takes_no_lock_that_blocks_writers(converged) -> None:
    tables = [
        row[0]
        for row in converged.execute(
            "SELECT quote_ident(relname) FROM pg_class "
            "WHERE relnamespace = current_schema()::regnamespace AND relkind = 'r'"
        ).fetchall()
    ]
    writer = db_helpers.connect()
    try:
        writer.execute(f"LOCK TABLE {', '.join(tables)} IN ROW EXCLUSIVE MODE")
        converged.execute("SET lock_timeout = '500ms'")
        converged.commit()
        schema_creation.converge_additive_schema(converged)
    finally:
        writer.rollback()
        writer.close()


def test_missing_column_is_added_in_its_own_transaction(converged, monkeypatch) -> None:
    converged.execute("ALTER TABLE deployment_runs DROP COLUMN settling_at")
    converged.commit()

    (guard,) = _converge_recording(converged, monkeypatch)

    assert _column_exists(converged, "deployment_runs", "settling_at")
    (change,) = _schema_changes(guard.executed)
    assert "settling_at" in change


def test_held_lock_retries_then_refuses_by_name(converged, monkeypatch) -> None:
    converged.execute("ALTER TABLE deployment_runs DROP COLUMN settling_at")
    converged.execute("SET lock_timeout = '100ms'")
    converged.commit()
    delays: list[float] = []
    monkeypatch.setattr(schema_converge_statements.time, "sleep", delays.append)
    holder = db_helpers.connect()
    try:
        holder.execute("LOCK TABLE deployment_runs IN ACCESS SHARE MODE")
        with pytest.raises(SchemaConvergeLockError) as refused:
            schema_creation.converge_additive_schema(converged)
    finally:
        holder.rollback()
        holder.close()

    assert refused.value.code == LOCK_UNAVAILABLE
    assert "deployment_runs" in str(refused.value)
    assert delays == list(schema_converge_statements.RETRY_DELAYS_SECONDS)
    assert not _column_exists(converged, "deployment_runs", "settling_at")


def test_each_table_commits_before_the_next_is_touched(converged, monkeypatch) -> None:
    converged.execute("ALTER TABLE deployment_runs DROP COLUMN settling_at")
    converged.execute("SET lock_timeout = '100ms'")
    converged.commit()
    monkeypatch.setattr(schema_converge_statements.time, "sleep", lambda _s: None)
    holder = db_helpers.connect()
    try:
        holder.execute("LOCK TABLE actors IN ACCESS SHARE MODE")
        with pytest.raises(SchemaConvergeLockError) as refused:
            with schema_converge_statements.converging_missing_schema(
                converged
            ) as guard:
                guard.execute(
                    "ALTER TABLE deployment_runs "
                    "ADD COLUMN IF NOT EXISTS settling_at TIMESTAMPTZ"
                )
                guard.execute("ALTER TABLE actors ADD COLUMN IF NOT EXISTS probe TEXT")
    finally:
        holder.rollback()
        holder.close()

    assert refused.value.tables == frozenset({"actors"})
    assert _column_exists(converged, "deployment_runs", "settling_at")
    assert not _column_exists(converged, "actors", "probe")
