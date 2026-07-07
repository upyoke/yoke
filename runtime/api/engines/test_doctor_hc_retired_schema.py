"""Tests for HC-retired-schema-resurrection (external sqlite_file + general).

Postgres-authority branch coverage lives in the sibling
``test_doctor_hc_retired_schema_postgres`` module; shared control-plane
connection builders live in ``_doctor_hc_retired_schema_test_helpers``.

The on-disk ``sqlite3.connect`` fixtures here are intentional: the subject
is the managed-project ``sqlite_file`` authoritative-DB branch the HC
probes on disk. Control-plane state rides Postgres test databases.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from unittest import mock

import pytest

from yoke_core.domain import retired_schema_registry as rsr
from yoke_core.engines.doctor_hc_retired_schema import (
    hc_retired_schema_resurrection,
)
from yoke_core.engines.doctor_report import DoctorArgs, RecordCollector
from yoke_core.engines._doctor_hc_retired_schema_test_helpers import (
    _make_control_conn,
    _write_registry,
)


@pytest.fixture(autouse=True)
def _clear_cache() -> None:
    rsr.clear_cache()
    yield
    rsr.clear_cache()


class TestRetiredSchemaResurrection:
    def test_pass_when_registry_empty(self, tmp_path: Path) -> None:
        _write_registry(tmp_path, "surfaces: []\n")
        auth = tmp_path / "authoritative.db"
        auth.touch()
        with mock.patch(
            "yoke_core.engines.doctor_hc_retired_schema.load_registry",
            return_value=[],
        ):
            conn = _make_control_conn(tmp_path, auth)
            try:
                rec = RecordCollector()
                hc_retired_schema_resurrection(conn, DoctorArgs(), rec)
            finally:
                conn.close()
        assert len(rec.results) == 1
        assert rec.results[0].result == "PASS"

    def test_pass_when_column_absent(self, tmp_path: Path) -> None:
        auth = tmp_path / "authoritative.db"
        # Staged external SQLite target WITHOUT the retired column present.
        with sqlite3.connect(str(auth)) as probe:
            probe.execute("CREATE TABLE projects (id TEXT PRIMARY KEY)")
            probe.commit()
        _write_registry(
            tmp_path,
            "surfaces:\n"
            "  - module: demo_cutover\n"
            "    project: buzz\n"
            "    model: primary\n"
            "    table: projects\n"
            "    column: retired_col\n",
        )
        rsr.clear_cache()
        # Point the registry loader at tmp_path.
        with mock.patch(
            "yoke_core.engines.doctor_hc_retired_schema.load_registry",
            return_value=rsr.load_registry(tmp_path, force_reload=True),
        ):
            conn = _make_control_conn(tmp_path, auth)
            try:
                rec = RecordCollector()
                hc_retired_schema_resurrection(conn, DoctorArgs(), rec)
            finally:
                conn.close()
        assert rec.results[0].result == "PASS"

    def test_warn_when_retired_column_present(self, tmp_path: Path) -> None:
        auth = tmp_path / "authoritative.db"
        # The external SQLite target still exposes the retired column — drift!
        with sqlite3.connect(str(auth)) as probe:
            probe.execute(
                "CREATE TABLE projects (id TEXT PRIMARY KEY, retired_col TEXT)"
            )
            probe.commit()
        _write_registry(
            tmp_path,
            "surfaces:\n"
            "  - module: demo_cutover\n"
            "    project: buzz\n"
            "    model: primary\n"
            "    table: projects\n"
            "    column: retired_col\n",
        )
        rsr.clear_cache()
        with mock.patch(
            "yoke_core.engines.doctor_hc_retired_schema.load_registry",
            return_value=rsr.load_registry(tmp_path, force_reload=True),
        ):
            conn = _make_control_conn(tmp_path, auth)
            try:
                rec = RecordCollector()
                hc_retired_schema_resurrection(conn, DoctorArgs(), rec)
            finally:
                conn.close()
        assert rec.results[0].result == "WARN"
        detail = rec.results[0].detail
        assert "projects.retired_col" in detail
        assert "demo_cutover" in detail
        # Remediation text names the reason.
        assert "Remediation" in detail

    def test_malformed_registry_surfaces_as_warn(
        self, tmp_path: Path
    ) -> None:
        auth = tmp_path / "authoritative.db"
        auth.touch()
        with mock.patch(
            "yoke_core.engines.doctor_hc_retired_schema.load_registry",
            side_effect=rsr.RetiredSchemaRegistryError("boom"),
        ):
            conn = _make_control_conn(tmp_path, auth)
            try:
                rec = RecordCollector()
                hc_retired_schema_resurrection(conn, DoctorArgs(), rec)
            finally:
                conn.close()
        assert rec.results[0].result == "WARN"
        assert "malformed" in rec.results[0].detail

    def test_pass_when_retired_table_absent(self, tmp_path: Path) -> None:
        # Authoritative DB has unrelated tables; the retired table is gone.
        auth = tmp_path / "authoritative.db"
        with sqlite3.connect(str(auth)) as probe:
            probe.execute("CREATE TABLE projects (id TEXT PRIMARY KEY)")
            probe.commit()
        _write_registry(
            tmp_path,
            "surfaces:\n"
            "  - module: drop_legacy_backup\n"
            "    project: buzz\n"
            "    model: primary\n"
            "    table: legacy_backup\n",
        )
        rsr.clear_cache()
        with mock.patch(
            "yoke_core.engines.doctor_hc_retired_schema.load_registry",
            return_value=rsr.load_registry(tmp_path, force_reload=True),
        ):
            conn = _make_control_conn(tmp_path, auth)
            try:
                rec = RecordCollector()
                hc_retired_schema_resurrection(conn, DoctorArgs(), rec)
            finally:
                conn.close()
        assert rec.results[0].result == "PASS"

    def test_warn_when_retired_table_present(
        self, tmp_path: Path
    ) -> None:
        # Authoritative DB still exposes the retired table — drift!
        auth = tmp_path / "authoritative.db"
        with sqlite3.connect(str(auth)) as probe:
            probe.execute(
                "CREATE TABLE legacy_backup "
                "(id INTEGER PRIMARY KEY, payload TEXT)"
            )
            probe.commit()
        _write_registry(
            tmp_path,
            "surfaces:\n"
            "  - module: drop_legacy_backup\n"
            "    project: buzz\n"
            "    model: primary\n"
            "    table: legacy_backup\n",
        )
        rsr.clear_cache()
        with mock.patch(
            "yoke_core.engines.doctor_hc_retired_schema.load_registry",
            return_value=rsr.load_registry(tmp_path, force_reload=True),
        ):
            conn = _make_control_conn(tmp_path, auth)
            try:
                rec = RecordCollector()
                hc_retired_schema_resurrection(conn, DoctorArgs(), rec)
            finally:
                conn.close()
        assert rec.results[0].result == "WARN"
        detail = rec.results[0].detail
        # Surface label distinguishes table-level from column-level.
        assert "buzz/legacy_backup" in detail
        assert "table-level" in detail
        assert "drop_legacy_backup" in detail
        assert "Remediation" in detail

    def test_mixed_table_and_column_entries_evaluated_independently(
        self, tmp_path: Path,
    ) -> None:
        # One table-level entry that is still present (drift), one
        # column-level entry whose column is absent (clean). The HC must
        # surface only the table-level finding.
        auth = tmp_path / "authoritative.db"
        with sqlite3.connect(str(auth)) as probe:
            probe.execute(
                "CREATE TABLE legacy_backup (id INTEGER PRIMARY KEY)"
            )
            probe.execute(
                "CREATE TABLE other_table (id TEXT PRIMARY KEY)"
            )
            probe.commit()
        _write_registry(
            tmp_path,
            "surfaces:\n"
            "  - module: drop_legacy_backup\n"
            "    project: buzz\n"
            "    model: primary\n"
            "    table: legacy_backup\n"
            "  - module: drop_other_col\n"
            "    project: buzz\n"
            "    model: primary\n"
            "    table: other_table\n"
            "    column: deprecated_col\n",
        )
        rsr.clear_cache()
        with mock.patch(
            "yoke_core.engines.doctor_hc_retired_schema.load_registry",
            return_value=rsr.load_registry(tmp_path, force_reload=True),
        ):
            conn = _make_control_conn(tmp_path, auth)
            try:
                rec = RecordCollector()
                hc_retired_schema_resurrection(conn, DoctorArgs(), rec)
            finally:
                conn.close()
        assert rec.results[0].result == "WARN"
        detail = rec.results[0].detail
        assert "legacy_backup" in detail
        # The column-level entry was clean — must NOT appear in detail.
        assert "deprecated_col" not in detail

    def test_skip_surfaces_when_schema_target_unresolvable(
        self, tmp_path: Path
    ) -> None:
        _write_registry(
            tmp_path,
            "surfaces:\n"
            "  - module: x\n"
            "    project: buzz\n"
            "    model: primary\n"
            "    table: projects\n"
            "    column: retired_col\n",
        )
        rsr.clear_cache()
        # Control DB with no capability row → resolver returns None.
        from runtime.api.fixtures import pg_testdb
        from runtime.api.fixtures.schema_ddl import apply_fixture_ddl

        db_name = pg_testdb.create_test_database()
        conn = pg_testdb.drop_database_on_close(
            pg_testdb.connect_test_database(db_name), db_name,
        )
        apply_fixture_ddl(
            conn,
            """
            CREATE TABLE projects (
                id INTEGER PRIMARY KEY,
                slug TEXT UNIQUE,
                name TEXT,
                public_item_prefix TEXT DEFAULT 'YOK'
            );
            CREATE TABLE project_capabilities (
                project_id INTEGER, type TEXT, config TEXT, settings TEXT,
                created_at TEXT
            );
            INSERT INTO projects (id, slug, name, public_item_prefix)
            VALUES (2, 'buzz', 'Buzz', 'BUZ');
            """
        )
        with mock.patch(
            "yoke_core.engines.doctor_hc_retired_schema.load_registry",
            return_value=rsr.load_registry(tmp_path, force_reload=True),
        ):
            rec = RecordCollector()
            hc_retired_schema_resurrection(conn, DoctorArgs(), rec)
        conn.close()
        assert rec.results[0].result == "WARN"
        assert "skipped" in rec.results[0].detail.lower()

    def test_yoke_sqlite_file_model_is_not_probed(
        self, tmp_path: Path
    ) -> None:
        auth = tmp_path / "authoritative.db"
        with sqlite3.connect(str(auth)) as probe:
            probe.execute(
                "CREATE TABLE projects (id TEXT PRIMARY KEY, retired_col TEXT)"
            )
            probe.commit()
        _write_registry(
            tmp_path,
            "surfaces:\n"
            "  - module: demo_cutover\n"
            "    project: yoke\n"
            "    model: primary\n"
            "    table: projects\n"
            "    column: retired_col\n",
        )
        rsr.clear_cache()
        with mock.patch(
            "yoke_core.engines.doctor_hc_retired_schema.load_registry",
            return_value=rsr.load_registry(tmp_path, force_reload=True),
        ):
            conn = _make_control_conn(tmp_path, auth, project="yoke")
            try:
                rec = RecordCollector()
                hc_retired_schema_resurrection(conn, DoctorArgs(), rec)
            finally:
                conn.close()
        assert rec.results[0].result == "WARN"
        detail = rec.results[0].detail
        assert "could not resolve schema target" in detail
        assert "still present" not in detail
