"""Tests for ``yoke_core.cli.raw_query``.

Covers default pipe separator, ``-separator`` override, pragmas applied, NULL
rendering, DDL/DML support, and exit semantics for SQL errors, missing
Postgres authority, and usage errors.
"""

from __future__ import annotations

import io
import os
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from typing import Tuple
from unittest import mock

import pytest

from yoke_core.cli import raw_query
from runtime.api.cli.raw_query_test_helpers import connect as _connect
from yoke_core.domain import db_backend
from yoke_core.domain.schema_common import _table_exists


def _fresh_db(tmp_path: Path) -> str:
    db_path = str(tmp_path / "test.db")
    conn = _connect(db_path)
    try:
        if db_backend.is_postgres():
            conn.execute("DROP TABLE IF EXISTS child")
            conn.execute("DROP TABLE IF EXISTS parent")
            conn.execute("DROP TABLE IF EXISTS extras")
            conn.execute("DROP TABLE IF EXISTS widgets")
        conn.execute(
            "CREATE TABLE widgets (id INTEGER PRIMARY KEY, name TEXT, qty INTEGER)"
        )
        conn.execute(
            "INSERT INTO widgets (id, name, qty) VALUES "
            "(1, 'alpha', 10), (2, 'beta', 20), (3, 'gamma', NULL)"
        )
        conn.commit()
    finally:
        conn.close()
    return db_path


def _run_exec(
    db_path: str, sql: str, separator: str = "|"
) -> Tuple[int, str, str]:
    out = io.StringIO()
    err = io.StringIO()
    rc = raw_query.execute_query(
        sql, separator=separator, db_path=db_path, out=out, err=err
    )
    return rc, out.getvalue(), err.getvalue()


# ---------------------------------------------------------------------------
# execute_query — select output shape
# ---------------------------------------------------------------------------


class TestExecuteSelectOutput:
    def test_default_separator_pipe(self, tmp_path: Path) -> None:
        db_path = _fresh_db(tmp_path)
        rc, out, err = _run_exec(db_path, "SELECT id, name, qty FROM widgets ORDER BY id")
        assert rc == 0
        assert err == ""
        # Default separator is '|', NULL → empty cell, trailing newline per row.
        assert out == "1|alpha|10\n2|beta|20\n3|gamma|\n"

    def test_custom_separator(self, tmp_path: Path) -> None:
        db_path = _fresh_db(tmp_path)
        rc, out, _ = _run_exec(
            db_path,
            "SELECT id, name, qty FROM widgets ORDER BY id",
            separator=";",
        )
        assert rc == 0
        assert out == "1;alpha;10\n2;beta;20\n3;gamma;\n"

    def test_single_column_select(self, tmp_path: Path) -> None:
        db_path = _fresh_db(tmp_path)
        rc, out, _ = _run_exec(
            db_path, "SELECT name FROM widgets ORDER BY id"
        )
        assert rc == 0
        assert out == "alpha\nbeta\ngamma\n"

    def test_empty_result_set_prints_nothing(self, tmp_path: Path) -> None:
        db_path = _fresh_db(tmp_path)
        rc, out, _ = _run_exec(db_path, "SELECT id FROM widgets WHERE id > 999")
        assert rc == 0
        assert out == ""

    def test_null_column_renders_empty(self, tmp_path: Path) -> None:
        db_path = _fresh_db(tmp_path)
        rc, out, _ = _run_exec(
            db_path, "SELECT name, qty FROM widgets WHERE id=3"
        )
        assert rc == 0
        assert out == "gamma|\n"

    def test_multiline_string_preserved(self, tmp_path: Path) -> None:
        db_path = _fresh_db(tmp_path)
        rc, out, _ = _run_exec(
            db_path, "SELECT 'first" + chr(10) + "second'"
        )
        assert rc == 0
        # sqlite3 CLI prints embedded newlines verbatim; we match.
        assert out == "first\nsecond\n"


# ---------------------------------------------------------------------------
# execute_query — DDL / DML
# ---------------------------------------------------------------------------


class TestExecuteDDLAndDML:
    def test_insert_commits_and_is_visible_after(self, tmp_path: Path) -> None:
        db_path = _fresh_db(tmp_path)
        rc, out, err = _run_exec(
            db_path, "INSERT INTO widgets (id, name, qty) VALUES (4, 'delta', 40)"
        )
        assert rc == 0
        assert out == ""
        assert err == ""

        # Verify via a fresh connection that it was actually committed.
        conn = _connect(db_path)
        qty = conn.execute("SELECT qty FROM widgets WHERE id=4").fetchone()[0]
        conn.close()
        assert qty == 40

    def test_update_commits(self, tmp_path: Path) -> None:
        db_path = _fresh_db(tmp_path)
        rc, out, _ = _run_exec(
            db_path, "UPDATE widgets SET qty=99 WHERE id=1"
        )
        assert rc == 0
        assert out == ""
        conn = _connect(db_path)
        qty = conn.execute("SELECT qty FROM widgets WHERE id=1").fetchone()[0]
        conn.close()
        assert qty == 99

    def test_create_table_succeeds(self, tmp_path: Path) -> None:
        db_path = _fresh_db(tmp_path)
        conn = _connect(db_path)
        conn.execute("DROP TABLE IF EXISTS extras")
        conn.commit()
        conn.close()
        rc, out, _ = _run_exec(
            db_path, "CREATE TABLE extras (k TEXT PRIMARY KEY)"
        )
        assert rc == 0
        assert out == ""
        conn = _connect(db_path)
        table_exists = _table_exists(conn, "extras")
        conn.close()
        assert table_exists


# ---------------------------------------------------------------------------
# execute_query — pragmas applied
# ---------------------------------------------------------------------------


class TestPragmas:
    def test_foreign_keys_on(self, tmp_path: Path) -> None:
        db_path = str(tmp_path / "fk.db")
        conn = _connect(db_path)
        try:
            if db_backend.is_postgres():
                conn.execute("DROP TABLE IF EXISTS child")
                conn.execute("DROP TABLE IF EXISTS parent")
            conn.execute("CREATE TABLE parent (id INTEGER PRIMARY KEY)")
            conn.execute(
                "CREATE TABLE child ("
                "id INTEGER PRIMARY KEY,"
                "parent_id INTEGER REFERENCES parent(id))"
            )
            conn.commit()
        finally:
            conn.close()
        rc, _out, err = _run_exec(
            db_path, "INSERT INTO child (id, parent_id) VALUES (1, 99)"
        )
        # foreign_keys=ON should make the INSERT fail with FK violation.
        assert rc == 1
        assert "FOREIGN KEY" in err or "foreign key" in err

    def test_busy_timeout_pragma_set(self, tmp_path: Path) -> None:
        if db_backend.is_postgres():
            rc, out, _ = _run_exec(str(tmp_path / "ignored.db"), "SELECT 1")
            assert rc == 0
            assert out.strip() == "1"
            return
        db_path = _fresh_db(tmp_path)
        rc, out, _ = _run_exec(db_path, "PRAGMA busy_timeout")
        assert rc == 0
        # Should reflect the applied value (5000) or higher.
        value = int(out.strip().splitlines()[0])
        assert value >= raw_query.BUSY_TIMEOUT_MS


# ---------------------------------------------------------------------------
# execute_query — error paths
# ---------------------------------------------------------------------------


class TestExecuteErrors:
    def test_missing_authority_returns_1(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv(
            "YOKE_PG_DSN",
            "host=/tmp/yoke-missing-pg-socket user=yoketest "
            "dbname=postgres connect_timeout=1",
        )
        rc, out, err = _run_exec(
            str(tmp_path / "does-not-exist.db"), "SELECT 1"
        )
        assert rc == 1
        assert out == ""
        assert "Error:" in err

    def test_sql_error_returns_1(self, tmp_path: Path) -> None:
        db_path = _fresh_db(tmp_path)
        rc, out, err = _run_exec(db_path, "SELECT * FROM no_such_table")
        assert rc == 1
        assert out == ""
        assert "Error:" in err

    def test_syntax_error_returns_1(self, tmp_path: Path) -> None:
        db_path = _fresh_db(tmp_path)
        rc, out, err = _run_exec(db_path, "NOT VALID SQL")
        assert rc == 1
        assert out == ""
        assert "Error:" in err


# ---------------------------------------------------------------------------
# main — CLI argument parsing
# ---------------------------------------------------------------------------


class TestMain:
    def _run_main(
        self, argv: list, *, db_path: str
    ) -> Tuple[int, str, str]:
        out = io.StringIO()
        err = io.StringIO()
        with mock.patch.dict(os.environ, {"YOKE_DB": db_path}), \
             redirect_stdout(out), redirect_stderr(err):
            rc = raw_query.main(argv)
        return rc, out.getvalue(), err.getvalue()

    def test_no_args_returns_2(self, tmp_path: Path) -> None:
        db_path = _fresh_db(tmp_path)
        rc, out, err = self._run_main([], db_path=db_path)
        assert rc == 2
        assert out == ""
        assert "query requires a SQL string" in err
        # usage banner now points at the Python entrypoint.
        assert 'python3 -m yoke_core.cli.db_router query' in err

    def test_bare_sql(self, tmp_path: Path) -> None:
        db_path = _fresh_db(tmp_path)
        rc, out, _ = self._run_main(
            ["SELECT id FROM widgets ORDER BY id"], db_path=db_path
        )
        assert rc == 0
        assert out == "1\n2\n3\n"

    def test_separator_flag(self, tmp_path: Path) -> None:
        db_path = _fresh_db(tmp_path)
        rc, out, _ = self._run_main(
            ["-separator", ";", "SELECT id, name FROM widgets ORDER BY id"],
            db_path=db_path,
        )
        assert rc == 0
        assert out == "1;alpha\n2;beta\n3;gamma\n"

    def test_separator_flag_without_sql_returns_2(self, tmp_path: Path) -> None:
        db_path = _fresh_db(tmp_path)
        rc, _out, err = self._run_main(["-separator", "|"], db_path=db_path)
        assert rc == 2
        assert "query requires a SQL string" in err

    def test_empty_sql_after_separator_returns_2(self, tmp_path: Path) -> None:
        db_path = _fresh_db(tmp_path)
        rc, _out, err = self._run_main(["-separator", "|", ""], db_path=db_path)
        assert rc == 2
        assert "query requires a SQL string" in err

    def test_empty_sql_returns_2(self, tmp_path: Path) -> None:
        db_path = _fresh_db(tmp_path)
        rc, _out, err = self._run_main([""], db_path=db_path)
        assert rc == 2
        assert "query requires a SQL string" in err

    def test_sql_error_via_main_returns_1(self, tmp_path: Path) -> None:
        db_path = _fresh_db(tmp_path)
        rc, out, err = self._run_main(
            ["SELECT * FROM no_such_table"], db_path=db_path
        )
        assert rc == 1
        assert out == ""
        assert "Error:" in err

    def test_module_invocation_roundtrip(self, tmp_path: Path) -> None:
        db_path = _fresh_db(tmp_path)
        rc, out, _ = self._run_main(
            ["SELECT name FROM widgets WHERE id=2"], db_path=db_path
        )
        assert rc == 0
        assert out == "beta\n"


# ---------------------------------------------------------------------------
# Custom separator edge cases
# ---------------------------------------------------------------------------


class TestSeparatorEdges:
    def test_multi_char_separator(self, tmp_path: Path) -> None:
        db_path = _fresh_db(tmp_path)
        rc, out, _ = _run_exec(
            db_path,
            "SELECT id, name FROM widgets ORDER BY id",
            separator="::",
        )
        assert rc == 0
        assert out == "1::alpha\n2::beta\n3::gamma\n"

    def test_tab_separator(self, tmp_path: Path) -> None:
        db_path = _fresh_db(tmp_path)
        rc, out, _ = _run_exec(
            db_path, "SELECT id, name FROM widgets ORDER BY id", separator="\t"
        )
        assert rc == 0
        assert out == "1\talpha\n2\tbeta\n3\tgamma\n"
