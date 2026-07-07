"""Tests for HC-retired-schema-resurrection — Postgres authority branch.

When a model declares ``authoritative_db.kind == 'postgres'`` the
authoritative DB *is* Yoke's connected control plane, so the HC probes
that same connection's catalog through the backend-aware ``schema_common``
helpers instead of opening a SQLite file. Before this branch existed the
postgres-authority surfaces were unresolvable and the HC emitted a
perpetual skip WARN; these cases lock in the live behaviour.

Shared scaffolding lives in ``_doctor_hc_retired_schema_test_helpers``;
the sqlite_file-authority cases live in the sibling
``test_doctor_hc_retired_schema`` module.
"""

from __future__ import annotations

from pathlib import Path
from unittest import mock

import pytest

from yoke_core.domain import retired_schema_registry as rsr
from yoke_core.engines.doctor_hc_retired_schema import (
    hc_retired_schema_resurrection,
)
from yoke_core.engines.doctor_report import DoctorArgs, RecordCollector
from yoke_core.engines._doctor_hc_retired_schema_test_helpers import (
    _make_pg_control_conn,
    _write_registry,
)


@pytest.fixture(autouse=True)
def _clear_cache() -> None:
    rsr.clear_cache()
    yield
    rsr.clear_cache()


class TestRetiredSchemaResurrectionPostgres:
    def test_pass_when_postgres_authority_surface_absent(
        self, tmp_path: Path
    ) -> None:
        """With a Postgres authority, the HC probes the connected control
        plane's catalog. An absent retired column reads as clean (PASS) —
        the pre-cutover perpetual-skip WARN is gone now that postgres
        authorities are resolvable."""
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
            with _make_pg_control_conn(tmp_path) as conn:
                rec = RecordCollector()
                hc_retired_schema_resurrection(conn, DoctorArgs(), rec)
        assert rec.results[0].result == "PASS"

    def test_warn_when_postgres_authority_column_present(
        self, tmp_path: Path
    ) -> None:
        """A retired column still present on the connected control plane is
        drift — WARN, with the surface and retiring module named."""
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
            with _make_pg_control_conn(tmp_path) as conn:
                conn.execute("ALTER TABLE projects ADD COLUMN retired_col TEXT")
                conn.commit()
                rec = RecordCollector()
                hc_retired_schema_resurrection(conn, DoctorArgs(), rec)
        assert rec.results[0].result == "WARN"
        detail = rec.results[0].detail
        assert "projects.retired_col" in detail
        assert "demo_cutover" in detail
        assert "Remediation" in detail

    def test_warn_when_postgres_authority_table_present(
        self, tmp_path: Path
    ) -> None:
        """A retired table still present on the connected control plane is
        drift — WARN, table-level."""
        _write_registry(
            tmp_path,
            "surfaces:\n"
            "  - module: drop_legacy_backup\n"
            "    project: yoke\n"
            "    model: primary\n"
            "    table: legacy_backup\n",
        )
        rsr.clear_cache()
        with mock.patch(
            "yoke_core.engines.doctor_hc_retired_schema.load_registry",
            return_value=rsr.load_registry(tmp_path, force_reload=True),
        ):
            with _make_pg_control_conn(tmp_path) as conn:
                conn.execute(
                    "CREATE TABLE legacy_backup "
                    "(id INTEGER PRIMARY KEY, payload TEXT)"
                )
                conn.commit()
                rec = RecordCollector()
                hc_retired_schema_resurrection(conn, DoctorArgs(), rec)
        assert rec.results[0].result == "WARN"
        detail = rec.results[0].detail
        assert "yoke/legacy_backup" in detail
        assert "table-level" in detail
        assert "drop_legacy_backup" in detail
