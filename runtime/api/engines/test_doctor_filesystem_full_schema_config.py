"""Doctor filesystem HC tests: schema sync, body, and config.

Helpers/doc-drift/agent HCs live in test_doctor_filesystem_full.py.
Hook + session HCs live in test_doctor_filesystem_full_hooks.py.
Repo file HCs live in test_doctor_filesystem_full_repo.py and
test_doctor_filesystem_full_repo2.py.

Schema scaffolding shared via _doctor_filesystem_full_test_helpers (private module).
"""

from __future__ import annotations

import json
import os

from unittest.mock import patch

from runtime.api.fixtures import pg_testdb
from runtime.api.fixtures.schema_ddl import apply_fixture_ddl
from yoke_core.engines.doctor import (
    hc_arch_consistency,
    hc_backlog_quality,
    hc_config_validation,
    hc_schema_script_sync,
    hc_stale_body,
)

from yoke_core.engines._doctor_filesystem_full_test_helpers import (
    _make_conn,
    _run_hc,
)


def _empty_conn():
    name = pg_testdb.create_test_database()
    return pg_testdb.drop_database_on_close(
        pg_testdb.connect_test_database(name), name
    )


class TestSchemaAndConfigChecks:
    def test_schema_script_sync_warns_when_item_db_script_missing(self, tmp_path):
        with patch("yoke_core.engines.doctor_report._resolve_repo_root", return_value=str(tmp_path)):
            rec = _run_hc(hc_schema_script_sync)
        assert rec.results[0].result == "WARN"
        assert "items.py not found" in rec.results[0].detail

    def test_schema_script_sync_warns_without_items_columns(self, tmp_path):
        conn = _empty_conn()
        with patch("yoke_core.engines.doctor_report._resolve_repo_root", return_value=str(tmp_path)):
            rec = _run_hc(hc_schema_script_sync, conn)
        assert rec.results[0].result == "WARN"
        assert "Could not read items table columns" in rec.results[0].detail

    def test_schema_script_sync_passes_when_python_surface_exists(self, tmp_path):
        module = tmp_path / "runtime" / "api" / "domain" / "items.py"
        module.parent.mkdir(parents=True)
        module.write_text("SELECT id, status FROM items;\n")
        with patch("yoke_core.engines.doctor_report._resolve_repo_root", return_value=str(tmp_path)):
            rec = _run_hc(hc_schema_script_sync)
        assert rec.results[0].result == "PASS"

    def test_config_validation_passes_without_repo_root(self):
        with patch("yoke_core.engines.doctor_report._resolve_repo_root", return_value=None):
            rec = _run_hc(hc_config_validation)
        assert rec.results[0].result == "PASS"

    def test_config_validation_warns_when_config_missing(self, tmp_path):
        missing = tmp_path / ".yoke" / "config.json"
        with patch.dict(os.environ, {"YOKE_MACHINE_CONFIG_FILE": str(missing)}):
            rec = _run_hc(hc_config_validation)
        assert rec.results[0].result == "WARN"
        assert "machine config not found" in rec.results[0].detail

    def test_config_validation_warns_on_invalid_json_shape(self, tmp_path):
        config_path = tmp_path / ".yoke" / "config.json"
        config_path.parent.mkdir()
        config_path.write_text('{"settings": "not-an-object"}\n')
        with patch.dict(os.environ, {"YOKE_MACHINE_CONFIG_FILE": str(config_path)}):
            rec = _run_hc(hc_config_validation)
        assert rec.results[0].result == "WARN"
        assert "settings must be an object" in rec.results[0].detail

    def test_config_validation_passes_with_machine_config(self, tmp_path):
        config_path = tmp_path / ".yoke" / "config.json"
        config_path.parent.mkdir()
        config_path.write_text(
            '{"settings": {"lane_paths_custom": "refine"}, "projects": {}}\n'
        )
        with patch.dict(os.environ, {"YOKE_MACHINE_CONFIG_FILE": str(config_path)}):
            rec = _run_hc(hc_config_validation)
        assert rec.results[0].result == "PASS"

    def test_config_validation_warns_on_dead_checkout_mapping(self, tmp_path):
        gone = tmp_path / "removed-worktree"
        config_path = tmp_path / ".yoke" / "config.json"
        config_path.parent.mkdir()
        config_path.write_text(
            json.dumps(
                {
                    "settings": {},
                    "projects": [
                        {
                            "checkout": str(gone),
                            "project_id": 3,
                            "env": "prod-db-admin",
                        }
                    ],
                }
            )
        )
        with patch.dict(os.environ, {"YOKE_MACHINE_CONFIG_FILE": str(config_path)}):
            rec = _run_hc(hc_config_validation)
        assert rec.results[0].result == "WARN"
        assert "checkout missing or not a git checkout" in rec.results[0].detail
        assert str(gone) in rec.results[0].detail
        assert "env=prod-db-admin" in rec.results[0].detail

    def test_config_validation_passes_when_checkout_mappings_exist(self, tmp_path):
        checkout = tmp_path / "checkout"
        (checkout / ".git").mkdir(parents=True)
        config_path = tmp_path / ".yoke" / "config.json"
        config_path.parent.mkdir()
        config_path.write_text(
            json.dumps(
                {
                    "settings": {},
                    "projects": [
                        {
                            "checkout": str(checkout),
                            "project_id": 1,
                            "env": "prod",
                        }
                    ],
                }
            )
        )
        with patch.dict(os.environ, {"YOKE_MACHINE_CONFIG_FILE": str(config_path)}):
            rec = _run_hc(hc_config_validation)
        assert rec.results[0].result == "PASS"

    def test_arch_consistency_passes_without_repo_root(self):
        with patch("yoke_core.engines.doctor_report._resolve_repo_root", return_value=None):
            rec = _run_hc(hc_arch_consistency)
        assert rec.results[0].result == "PASS"

    def test_arch_consistency_warns_on_retired_artifacts_and_schema_gaps(self, tmp_path):
        conn = _make_conn()
        backlog_dir = tmp_path / "data" / "backlog"
        backlog_dir.mkdir(parents=True)
        (backlog_dir / ".counter").write_text("1\n")
        with patch("yoke_core.engines.doctor_report._resolve_repo_root", return_value=str(tmp_path)):
            rec = _run_hc(hc_arch_consistency, conn)
        assert rec.results[0].result == "WARN"
        assert "Retired root data directory still exists" in rec.results[0].detail
        assert "Schema gap" in rec.results[0].detail

    def test_arch_consistency_passes_when_schema_is_complete(self, tmp_path):
        conn = _make_conn()
        apply_fixture_ddl(
            conn,
            """
            CREATE TABLE ouroboros_entries (id INTEGER PRIMARY KEY);
            CREATE TABLE wrapup_reports (id INTEGER PRIMARY KEY);
            CREATE TABLE epic_tasks (id INTEGER PRIMARY KEY);
            """,
        )
        with patch("yoke_core.engines.doctor_report._resolve_repo_root", return_value=str(tmp_path)):
            rec = _run_hc(hc_arch_consistency, conn)
        assert rec.results[0].result == "PASS"


class TestStaleBody:
    def test_passes_when_spec_updated_at_present(self):
        conn = _make_conn()
        conn.execute(
            "INSERT INTO items (id, status, spec_updated_at) "
            "VALUES (1, 'implementing', '2024-01-02T00:00:00Z')"
        )
        rec = _run_hc(hc_stale_body, conn)
        assert rec.results[0].result == "PASS"

    def test_passes_when_no_spec_updated_at(self):
        conn = _make_conn()
        conn.execute(
            "INSERT INTO items (id, status) "
            "VALUES (1, 'implementing')"
        )
        rec = _run_hc(hc_stale_body, conn)
        assert rec.results[0].result == "PASS"


class TestBacklogQualityConfigParsing:
    def test_ignores_invalid_backlog_stale_days_config(self, tmp_path):
        conn = _empty_conn()
        apply_fixture_ddl(
            conn,
            """
            CREATE TABLE items (
                id INTEGER PRIMARY KEY,
                status TEXT,
                created_at TEXT,
                title TEXT,
                priority TEXT,
                spec TEXT
            );
            """,
        )
        conn.execute(
            "INSERT INTO items (id, status, created_at, title, priority, spec) "
            "VALUES (1, 'idea', '2024-01-01T00:00:00Z', 'Valid long title', 'medium', '# Valid long title')"
        )
        data_root = tmp_path / "data"
        data_root.mkdir()
        (data_root / "config").write_text("backlog_stale_days=not-a-number\n")
        with patch("yoke_core.engines.doctor_report._resolve_repo_root", return_value=str(tmp_path)):
            rec = _run_hc(hc_backlog_quality, conn)
        assert rec.results[0].result in ("PASS", "WARN")
