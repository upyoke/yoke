"""Tests for yoke_core.domain.db_helpers — connection + query helpers.

Covers connect(), query_scalar(), query_rows(), query_one(), iso8601_now(),
and the conftest fixture round-trip helpers. Path resolution lives in
test_db_helpers.py.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest import mock

import pytest

from yoke_core.domain import db_backend
from yoke_core.domain.db_helpers import (
    iso8601_now,
    query_one,
    query_rows,
    query_scalar,
)
from yoke_core.domain.schema_common import _table_exists
from runtime.api.fixtures.file_test_db import (
    apply_inline_ddl,
    connect_test_db,
    init_test_db,
)


def _seed_simple_items_table() -> None:
    """``init_test_db`` ``apply_schema`` strategy for the query helpers.

    Builds the three-column ``items`` table the query-helper tests exercise
    (deliberately NOT the production ``items`` schema) and seeds three rows.
    Resolves its own connection through the backend factory (``YOKE_DB`` on
    SQLite, the repointed per-test ``YOKE_PG_DSN`` on Postgres), so each test
    gets an isolated table that never collides with the ambient production
    ``items`` relation on Postgres.
    """
    conn = db_backend.connect()
    try:
        conn.execute(
            "CREATE TABLE items (id INTEGER PRIMARY KEY, name TEXT, val INTEGER)"
        )
        conn.execute("INSERT INTO items VALUES (1, 'alpha', 10)")
        conn.execute("INSERT INTO items VALUES (2, 'beta', 20)")
        conn.execute("INSERT INTO items VALUES (3, 'gamma', 30)")
        conn.commit()
    finally:
        conn.close()


@pytest.fixture
def mem_conn(tmp_path: Path):
    """Per-test connection with a simple three-column ``items`` table.

    The table lives in a disposable per-test Postgres database (dropped on
    teardown), isolated from the ambient production schema.
    """
    with init_test_db(tmp_path, apply_schema=_seed_simple_items_table) as path:
        conn = connect_test_db(path)
        try:
            yield conn
        finally:
            conn.close()


def test_connect_test_db_returns_native_psycopg_row_family(tmp_path: Path) -> None:
    with init_test_db(
        tmp_path,
        apply_schema=lambda: apply_inline_ddl(
            "CREATE TABLE native_probe (id INTEGER PRIMARY KEY, name TEXT);"
        ),
    ) as path:
        conn = connect_test_db(path)
        try:
            assert db_backend.connection_is_postgres(conn)
            assert not hasattr(conn, "executescript")
            conn.execute(
                "INSERT INTO native_probe (id, name) VALUES (%s, %s)",
                (1, "native"),
            )
            row = conn.execute(
                "SELECT id, name FROM native_probe WHERE id = %s",
                (1,),
            ).fetchone()
            assert row[0] == 1
            assert row["name"] == "native"
        finally:
            conn.close()


class TestQueryRows:
    """Test query_rows returns all matching rows."""

    def test_all_rows(self, mem_conn: Any) -> None:
        rows = query_rows(mem_conn, "SELECT * FROM items ORDER BY id")
        assert len(rows) == 3
        assert rows[0]["name"] == "alpha"
        assert rows[2]["name"] == "gamma"

    def test_with_params(self, mem_conn: Any) -> None:
        rows = query_rows(
            mem_conn, "SELECT * FROM items WHERE val > %s", (15,)
        )
        assert len(rows) == 2

    def test_empty_result(self, mem_conn: Any) -> None:
        rows = query_rows(
            mem_conn, "SELECT * FROM items WHERE val > %s", (100,)
        )
        assert rows == []


class TestQueryOne:
    """Test query_one returns first row or None."""

    def test_returns_row(self, mem_conn: Any) -> None:
        row = query_one(mem_conn, "SELECT * FROM items WHERE id = %s", (2,))
        assert row is not None
        assert row["name"] == "beta"

    def test_returns_none_when_no_match(self, mem_conn: Any) -> None:
        row = query_one(mem_conn, "SELECT * FROM items WHERE id = %s", (999,))
        assert row is None


class TestQueryScalar:
    """Test query_scalar returns first column of first row."""

    def test_returns_scalar(self, mem_conn: Any) -> None:
        result = query_scalar(mem_conn, "SELECT COUNT(*) FROM items")
        assert result == 3

    def test_returns_none_when_no_match(self, mem_conn: Any) -> None:
        result = query_scalar(
            mem_conn, "SELECT name FROM items WHERE id = %s", (999,)
        )
        assert result is None

    def test_returns_string_scalar(self, mem_conn: Any) -> None:
        result = query_scalar(
            mem_conn, "SELECT name FROM items WHERE id = %s", (1,)
        )
        assert result == "alpha"


class TestIso8601Now:
    """Canonical UTC ISO-8601 helper.

    Used by callers that need Python-owned UTC timestamps instead of
    SQLite-only column defaults.
    """

    def test_format_matches_canonical(self) -> None:
        """Returns ``YYYY-MM-DDTHH:MM:SSZ`` — sortable, round-trips cleanly."""
        import re

        value = iso8601_now()
        assert re.match(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$", value), value

    def test_returns_str(self) -> None:
        assert isinstance(iso8601_now(), str)

    def test_round_trip_through_fromisoformat(self) -> None:
        """Python's ``datetime.fromisoformat`` parses the value after the
        SQL-friendly ``Z → +00:00`` normalization."""
        from datetime import datetime

        value = iso8601_now()
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        assert parsed.tzinfo is not None
        assert parsed.utcoffset().total_seconds() == 0

    def test_utc_when_system_tz_is_not_utc(self) -> None:
        """Value reflects UTC even when the clock mock reports a non-UTC
        wall-clock — we assert formatter UTC-correctness by monkeypatching
        ``datetime.now`` to return a fixed UTC-aware value and checking the
        exact output string."""
        from datetime import datetime as real_datetime, timezone

        frozen = real_datetime(2026, 6, 15, 12, 34, 56, tzinfo=timezone.utc)

        class _FrozenDT:
            @staticmethod
            def now(tz=None):  # noqa: D401 - mimic datetime.now signature
                return frozen.astimezone(tz) if tz is not None else frozen

        with mock.patch("yoke_core.domain.db_helpers.datetime", _FrozenDT):
            assert iso8601_now() == "2026-06-15T12:34:56Z"


class TestConftest:
    """Test that conftest fixtures work for basic insert/query patterns."""

    def test_test_db_creates_tables(self, test_db: Any) -> None:
        """test_db fixture creates all required tables."""
        required = {
            "items",
            "epic_tasks",
            "events",
            "deployment_runs",
            "deployment_run_items",
            "qa_requirements",
            "qa_runs",
            "qa_artifacts",
            "projects",
            "deployment_flows",
            "severity_config",
            "event_registry",
        }
        missing = {table for table in required if not _table_exists(test_db, table)}
        assert not missing, f"Missing tables: {missing}"

    def test_insert_and_query_item(self, test_db: Any) -> None:
        """insert_item + query round-trip."""
        from runtime.api.conftest import insert_item

        row = insert_item(test_db, id=42, title="Hello", status="idea")
        assert row["id"] == 42
        assert row["title"] == "Hello"

        fetched = query_one(test_db, "SELECT * FROM items WHERE id = %s", (42,))
        assert fetched["title"] == "Hello"

    def test_insert_epic_task(self, test_db: Any) -> None:
        """insert_epic_task round-trip."""
        from runtime.api.conftest import insert_epic_task

        row = insert_epic_task(test_db, epic_id=10, task_num=1, title="Task A")
        assert row["epic_id"] == 10
        assert row["task_num"] == 1

    def test_insert_event(self, test_db: Any) -> None:
        """insert_event round-trip."""
        from runtime.api.conftest import insert_event

        row = insert_event(test_db, event_name="TestEvt")
        assert row["event_name"] == "TestEvt"

    def test_insert_deployment_run(self, test_db: Any) -> None:
        """insert_deployment_run round-trip with auto-created project/flow."""
        from runtime.api.conftest import insert_deployment_run

        row = insert_deployment_run(test_db, id="run-1", project="testproj")
        assert row["id"] == "run-1"
        assert row["project_id"] > 0

    def test_insert_qa_requirement_and_run(
        self, test_db: Any
    ) -> None:
        """insert_qa_requirement + insert_qa_run round-trip."""
        from runtime.api.conftest import (
            insert_item,
            insert_qa_requirement,
            insert_qa_run,
        )

        insert_item(test_db, id=1)
        req = insert_qa_requirement(test_db, item_id=1, qa_kind="smoke")
        assert req["qa_kind"] == "smoke"

        run = insert_qa_run(
            test_db, qa_requirement_id=req["id"], verdict="pass"
        )
        assert run["verdict"] == "pass"
