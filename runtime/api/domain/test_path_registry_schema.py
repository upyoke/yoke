"""Schema tests for the canonical path registry tables."""

from __future__ import annotations

from pathlib import Path

import pytest

from yoke_core.domain import db_backend
from yoke_core.domain.events_schema import ensure_event_schema
from yoke_core.domain.path_registry import KIND_FILE
from yoke_core.domain.schema_common import (
    _get_check_constraint_defs,
    _get_column_default,
    _get_columns,
    _get_columns_with_types,
    _get_indexes,
    _table_create_sql,
    _table_exists,
)
from yoke_core.domain.schema_init_tables import create_path_registry_tables
from runtime.api.fixtures.file_test_db import connect_test_db, init_test_db

NOW = "2026-04-29T00:00:00Z"


def _apply_path_registry_schema() -> None:
    conn = db_backend.connect()
    try:
        p = "%s" if db_backend.connection_is_postgres(conn) else "?"
        conn.execute(
            "CREATE TABLE IF NOT EXISTS projects ("
            "id INTEGER PRIMARY KEY, slug TEXT UNIQUE NOT NULL, "
            "name TEXT NOT NULL, "
            "default_branch TEXT NOT NULL DEFAULT 'main', github_repo TEXT, "
            "public_item_prefix TEXT NOT NULL DEFAULT 'YOK', "
            "created_at TEXT NOT NULL)"
        )
        conn.execute(
            "INSERT INTO projects (id, slug, name, created_at) "
            f"VALUES ({p}, {p}, {p}, {p})",
            (4, "p", "p", NOW),
        )
        ensure_event_schema(conn)
        create_path_registry_tables(conn)
        conn.commit()
    finally:
        conn.close()


@pytest.fixture
def fresh_db(tmp_path: Path):
    with init_test_db(tmp_path, apply_schema=_apply_path_registry_schema) as db_path:
        conn = connect_test_db(db_path)
        try:
            yield conn
        finally:
            conn.close()


def _integrity_error_types(conn) -> tuple[type[Exception], ...]:
    return db_backend.integrity_error_types(conn)


def _p(conn) -> str:
    return "%s"


class TestSchema:
    def test_path_targets_columns(self, fresh_db):
        names = set(_get_columns(fresh_db, "path_targets"))
        assert set(names) == {
            "id", "project_id", "kind", "path_string",
            "generation", "parent_target_id", "created_at",
            "materialization_state", "materialization_updated_at",
            "planned_by_item_id", "planned_by_claim_id",
        }

    def test_path_targets_kind_is_open_text(self, fresh_db):
        column_types = dict(_get_columns_with_types(fresh_db, "path_targets"))
        assert column_types["kind"].lower() == "text"
        constraints = "\n".join(
            _get_check_constraint_defs(fresh_db, "path_targets")
        ).lower()
        assert "kind text not null check" not in constraints
        assert "check(kind in" not in constraints

    def test_path_targets_has_no_autoincrement(self, fresh_db):
        ddl = _table_create_sql(fresh_db, "path_targets")
        if ddl is None:
            pytest.skip("AUTOINCREMENT is SQLite DDL text, not a Postgres catalog fact")
        assert "AUTOINCREMENT" not in ddl.upper()

    def test_path_targets_no_timestamp_defaults(self, fresh_db):
        for column in ("created_at", "materialization_updated_at"):
            default = _get_column_default(fresh_db, "path_targets", column)
            assert default is None

    def test_required_indexes_exist(self, fresh_db):
        names = set(_get_indexes(fresh_db))
        assert "uq_path_targets_generation" in names
        assert "idx_path_targets_lookup" in names
        assert "idx_path_targets_parent" in names
        assert "idx_path_snapshot_entries_target" in names

    def test_path_snapshots_unique_per_project_commit(self, fresh_db):
        p = _p(fresh_db)
        fresh_db.execute(
            "INSERT INTO path_snapshots "
            f"(project_id, commit_sha, built_at) VALUES ({p}, {p}, {p})",
            (4, "abc", NOW),
        )
        with pytest.raises(_integrity_error_types(fresh_db)):
            fresh_db.execute(
                "INSERT INTO path_snapshots "
                f"(project_id, commit_sha, built_at) VALUES ({p}, {p}, {p})",
                (4, "abc", NOW),
            )

    def test_path_snapshot_entries_composite_pk(self, fresh_db):
        p = _p(fresh_db)
        cur = fresh_db.execute(
            "INSERT INTO path_targets "
            "(project_id, kind, path_string, generation, "
            f"parent_target_id, created_at) VALUES ({p}, {p}, {p}, {p}, {p}, {p}) "
            "RETURNING id",
            (4, KIND_FILE, "a", 1, None, NOW),
        )
        target_id = int(cur.fetchone()[0])
        cur = fresh_db.execute(
            "INSERT INTO path_snapshots "
            f"(project_id, commit_sha, built_at) VALUES ({p}, {p}, {p}) "
            "RETURNING id",
            (4, "abc", NOW),
        )
        snap_id = int(cur.fetchone()[0])
        fresh_db.execute(
            "INSERT INTO path_snapshot_entries (snapshot_id, target_id) "
            f"VALUES ({p}, {p})",
            (snap_id, target_id),
        )
        with pytest.raises(_integrity_error_types(fresh_db)):
            fresh_db.execute(
                "INSERT INTO path_snapshot_entries "
                f"(snapshot_id, target_id) VALUES ({p}, {p})",
                (snap_id, target_id),
            )

    def test_path_continuity_tables_created(self, fresh_db):
        """path continuity layer lands ``path_moves`` and ``path_context_values`` alongside
        the path-registry trio; later phases (e.g. ``recording_actors``)
        remain unshipped and must not be created."""
        assert _table_exists(fresh_db, "path_moves")
        assert _table_exists(fresh_db, "path_context_values")
        assert not _table_exists(fresh_db, "recording_actors")

    def test_path_snapshot_entries_carries_enrichment_columns(self, fresh_db):
        """architecture-fitness adds architecture-fitness enrichment columns to
        ``path_snapshot_entries``. Fresh-install DDL must carry them so
        new projects do not need the one-shot migration to read/write
        the columns."""
        names = set(_get_columns(fresh_db, "path_snapshot_entries"))
        assert {
            "line_count",
            "language",
            "module_name",
            "area",
            "is_generated",
            "dependency_edges",
        } <= names

    def test_enrichment_columns_have_lazy_backfill_defaults(self, fresh_db):
        """Existing-row backfill is lazy (next snapshot pass repopulates).
        Defaults must let an INSERT omit the new columns without raising
        — line_count/language/module_name/area default NULL, is_generated
        defaults 0, dependency_edges defaults '[]'."""
        p = _p(fresh_db)
        cur = fresh_db.execute(
            "INSERT INTO path_targets "
            "(project_id, kind, path_string, generation, "
            f"parent_target_id, created_at) VALUES ({p}, {p}, {p}, {p}, {p}, {p}) "
            "RETURNING id",
            (4, KIND_FILE, "a", 1, None, NOW),
        )
        target_id = int(cur.fetchone()[0])
        cur = fresh_db.execute(
            "INSERT INTO path_snapshots "
            f"(project_id, commit_sha, built_at) VALUES ({p}, {p}, {p}) "
            "RETURNING id",
            (4, "abc", NOW),
        )
        snap_id = int(cur.fetchone()[0])
        fresh_db.execute(
            "INSERT INTO path_snapshot_entries (snapshot_id, target_id) "
            f"VALUES ({p}, {p})",
            (snap_id, target_id),
        )
        row = fresh_db.execute(
            "SELECT line_count, language, module_name, area, "
            "is_generated, dependency_edges FROM path_snapshot_entries "
            f"WHERE snapshot_id={p} AND target_id={p}",
            (snap_id, target_id),
        ).fetchone()
        assert row[0] is None  # line_count
        assert row[1] is None  # language
        assert row[2] is None  # module_name
        assert row[3] is None  # area
        assert row[4] == 0     # is_generated
        assert row[5] == "[]"  # dependency_edges
