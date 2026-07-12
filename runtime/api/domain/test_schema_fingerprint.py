"""Tests for schema_fingerprint."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from yoke_core.domain import db_backend
from runtime.api.fixtures.file_test_db import init_test_db
from yoke_core.domain.schema_fingerprint import (
    FRESHNESS_WINDOW_MINUTES,
    SUPPORTED_KINDS,
    UnsupportedFingerprintKindError,
    fingerprint_kind,
    freshness_expired,
)


class TestFingerprintSupportedKinds:
    def test_sqlite_file_is_live(self) -> None:
        assert "sqlite_file" in SUPPORTED_KINDS

    def test_postgres_is_live(self) -> None:
        assert "postgres" in SUPPORTED_KINDS

    def test_mysql_raises(self) -> None:
        with pytest.raises(UnsupportedFingerprintKindError):
            fingerprint_kind("mysql", "/tmp/ignored.db")


class TestSqliteFingerprint:
    def _seed(self, path: Path) -> None:
        conn = sqlite3.connect(str(path))
        try:
            conn.execute("CREATE TABLE widgets (id INTEGER PRIMARY KEY, name TEXT)")
            conn.execute("CREATE INDEX idx_widgets_name ON widgets(name)")
            conn.commit()
        finally:
            conn.close()

    def test_stable_across_calls(self, tmp_path: Path) -> None:
        db = tmp_path / "fp.db"
        self._seed(db)
        first = fingerprint_kind("sqlite_file", str(db))
        second = fingerprint_kind("sqlite_file", str(db))
        assert first == second

    def test_changes_when_ddl_changes(self, tmp_path: Path) -> None:
        db = tmp_path / "fp.db"
        self._seed(db)
        before = fingerprint_kind("sqlite_file", str(db))
        conn = sqlite3.connect(str(db))
        try:
            conn.execute("ALTER TABLE widgets ADD COLUMN created_at TEXT")
            conn.commit()
        finally:
            conn.close()
        after = fingerprint_kind("sqlite_file", str(db))
        assert before != after

    def test_ignores_row_changes(self, tmp_path: Path) -> None:
        """Fingerprint is schema-only; row-data churn must not move it."""
        db = tmp_path / "fp.db"
        self._seed(db)
        before = fingerprint_kind("sqlite_file", str(db))
        conn = sqlite3.connect(str(db))
        try:
            conn.executemany(
                "INSERT INTO widgets (name) VALUES (?)",
                [("alpha",), ("beta",), ("gamma",)],
            )
            conn.commit()
        finally:
            conn.close()
        after = fingerprint_kind("sqlite_file", str(db))
        assert before == after

    def test_ignores_sqlite_internal_objects(self, tmp_path: Path) -> None:
        """Generic sqlite_file catalogs carry internal objects after ANALYZE.

        This SQLite catalog behavior is not a Yoke authority read; the
        fingerprint must exclude those internal rows to stay stable across
        incidental operational churn.
        """
        db = tmp_path / "fp.db"
        self._seed(db)
        before = fingerprint_kind("sqlite_file", str(db))
        conn = sqlite3.connect(str(db))
        try:
            conn.execute("ANALYZE")
            conn.commit()
        finally:
            conn.close()
        after = fingerprint_kind("sqlite_file", str(db))
        assert before == after

    def test_accepts_connection(self, tmp_path: Path) -> None:
        db = tmp_path / "fp.db"
        self._seed(db)
        conn = sqlite3.connect(str(db))
        try:
            from_conn = fingerprint_kind("sqlite_file", conn)
        finally:
            conn.close()
        from_path = fingerprint_kind("sqlite_file", str(db))
        assert from_conn == from_path

    def test_rejects_root_yoke_db_path(self, tmp_path: Path) -> None:
        db = tmp_path / "data" / "yoke.db"
        db.parent.mkdir()
        self._seed(db)
        with pytest.raises(ValueError, match="retired Yoke control-plane"):
            fingerprint_kind("sqlite_file", str(db))

    def test_rejects_root_yoke_db_connection(self, tmp_path: Path) -> None:
        db = tmp_path / "data" / "yoke.db"
        db.parent.mkdir()
        self._seed(db)
        conn = sqlite3.connect(str(db))
        try:
            with pytest.raises(ValueError, match="retired Yoke control-plane"):
                fingerprint_kind("sqlite_file", conn)
        finally:
            conn.close()


def _apply_postgres_fingerprint_schema() -> None:
    conn = db_backend.connect()
    try:
        conn.execute("CREATE TABLE widgets (id INTEGER PRIMARY KEY, name TEXT)")
        conn.execute("CREATE INDEX idx_widgets_name ON widgets(name)")
        conn.commit()
    finally:
        conn.close()


def _apply_postgres_semantic_schema() -> None:
    conn = db_backend.connect()
    try:
        conn.execute("CREATE TABLE parents (id INTEGER PRIMARY KEY)")
        conn.execute(
            "CREATE TABLE widgets (id INTEGER PRIMARY KEY, parent_id INTEGER,"
            " name TEXT)"
        )
        conn.execute(
            "ALTER TABLE widgets ADD CONSTRAINT widgets_parent_fk"
            " FOREIGN KEY (parent_id) REFERENCES parents(id) NOT VALID"
        )
        conn.execute("CREATE VIEW widget_names AS SELECT id, name FROM widgets")
        conn.execute(
            "CREATE FUNCTION keep_widget() RETURNS trigger LANGUAGE plpgsql"
            " AS $$ BEGIN RETURN NEW; END $$"
        )
        conn.execute(
            "CREATE TRIGGER keep_widget BEFORE INSERT ON widgets"
            " FOR EACH ROW EXECUTE FUNCTION keep_widget()"
        )
        conn.execute("ALTER TABLE widgets ENABLE ROW LEVEL SECURITY")
        conn.execute("CREATE POLICY widget_reader ON widgets TO PUBLIC USING (true)")
        conn.commit()
    finally:
        conn.close()


class TestPostgresFingerprint:
    postgres_only = pytest.mark.skipif(
        not db_backend.is_postgres(),
        reason="Postgres fingerprint requires the Postgres test cluster",
    )

    @postgres_only
    def test_stable_across_calls(self, tmp_path: Path) -> None:
        with init_test_db(tmp_path, apply_schema=_apply_postgres_fingerprint_schema):
            conn = db_backend.connect()
            try:
                first = fingerprint_kind("postgres", conn)
                second = fingerprint_kind("postgres", conn)
            finally:
                conn.close()
        assert first == second

    @postgres_only
    def test_accepts_dsn_string(self, tmp_path: Path) -> None:
        with init_test_db(tmp_path, apply_schema=_apply_postgres_fingerprint_schema):
            conn = db_backend.connect()
            try:
                from_conn = fingerprint_kind("postgres", conn)
                from_dsn = fingerprint_kind("postgres", db_backend.resolve_pg_dsn())
            finally:
                conn.close()
        assert from_dsn == from_conn

    @postgres_only
    def test_changes_when_ddl_changes(self, tmp_path: Path) -> None:
        with init_test_db(tmp_path, apply_schema=_apply_postgres_fingerprint_schema):
            conn = db_backend.connect()
            try:
                before = fingerprint_kind("postgres", conn)
                conn.execute("ALTER TABLE widgets ADD COLUMN created_at TEXT")
                conn.commit()
                after = fingerprint_kind("postgres", conn)
            finally:
                conn.close()
        assert before != after

    @postgres_only
    def test_ignores_row_changes(self, tmp_path: Path) -> None:
        with init_test_db(tmp_path, apply_schema=_apply_postgres_fingerprint_schema):
            conn = db_backend.connect()
            try:
                before = fingerprint_kind("postgres", conn)
                conn.execute(
                    "INSERT INTO widgets (id, name) VALUES (%s, %s)",
                    (1, "alpha"),
                )
                conn.commit()
                after = fingerprint_kind("postgres", conn)
            finally:
                conn.close()
        assert before == after

    @postgres_only
    @pytest.mark.parametrize(
        "ddl",
        (
            "ALTER TABLE widgets SET UNLOGGED",
            "ALTER TABLE widgets SET (fillfactor = 70)",
            "ALTER TABLE widgets ENABLE ROW LEVEL SECURITY",
            "ALTER TABLE widgets FORCE ROW LEVEL SECURITY",
            'ALTER TABLE widgets ALTER COLUMN name TYPE TEXT COLLATE "C"',
        ),
    )
    def test_changes_for_table_storage_security_and_collation(
        self, tmp_path: Path, ddl: str
    ) -> None:
        with init_test_db(tmp_path, apply_schema=_apply_postgres_fingerprint_schema):
            conn = db_backend.connect()
            try:
                before = fingerprint_kind("postgres", conn)
                conn.execute(ddl)
                conn.commit()
                after = fingerprint_kind("postgres", conn)
            finally:
                conn.close()
        assert before != after

    @postgres_only
    @pytest.mark.parametrize(
        "ddl",
        (
            "ALTER TABLE widgets DISABLE TRIGGER keep_widget",
            "ALTER VIEW widget_names SET (security_barrier = true)",
            "ALTER POLICY widget_reader ON widgets TO CURRENT_USER",
            "ALTER TABLE widgets VALIDATE CONSTRAINT widgets_parent_fk",
        ),
    )
    def test_changes_for_runtime_schema_semantics(
        self, tmp_path: Path, ddl: str
    ) -> None:
        with init_test_db(tmp_path, apply_schema=_apply_postgres_semantic_schema):
            conn = db_backend.connect()
            try:
                before = fingerprint_kind("postgres", conn)
                conn.execute(ddl)
                conn.commit()
                after = fingerprint_kind("postgres", conn)
            finally:
                conn.close()
        assert before != after


class TestFreshnessWindow:
    def test_just_rehearsed_not_expired(self) -> None:
        assert not freshness_expired(
            "2026-04-23T12:00:00Z",
            now="2026-04-23T12:05:00Z",
        )

    def test_within_window_not_expired(self) -> None:
        assert not freshness_expired(
            "2026-04-23T12:00:00Z",
            now="2026-04-23T12:29:00Z",
        )

    def test_at_window_boundary_not_expired(self) -> None:
        # Boundary: exactly 30 minutes = not expired (strict '>').
        assert not freshness_expired(
            "2026-04-23T12:00:00Z",
            now="2026-04-23T12:30:00Z",
        )

    def test_past_window_expired(self) -> None:
        assert freshness_expired(
            "2026-04-23T12:00:00Z",
            now="2026-04-23T12:31:00Z",
        )

    def test_missing_rehearsed_at_expired(self) -> None:
        assert freshness_expired(None)
        assert freshness_expired("")

    def test_malformed_rehearsed_at_expired(self) -> None:
        assert freshness_expired("not-a-timestamp")
        assert freshness_expired("2026-99-99T99:99:99Z")

    def test_custom_window(self) -> None:
        # A 5-minute window tightens freshness accordingly.
        assert freshness_expired(
            "2026-04-23T12:00:00Z",
            now="2026-04-23T12:06:00Z",
            window_minutes=5,
        )
        assert not freshness_expired(
            "2026-04-23T12:00:00Z",
            now="2026-04-23T12:04:00Z",
            window_minutes=5,
        )

    def test_plus_00_format_accepted(self) -> None:
        # db_helpers.iso8601_now emits 'Z', but +00:00 offset is the
        # canonical alternate UTC shape — both must parse.
        assert not freshness_expired(
            "2026-04-23T12:00:00+00:00",
            now="2026-04-23T12:05:00+00:00",
        )

    def test_default_window_is_thirty_minutes(self) -> None:
        assert FRESHNESS_WINDOW_MINUTES == 30
