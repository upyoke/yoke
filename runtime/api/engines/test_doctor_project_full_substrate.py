"""Tests for substrate, vocabulary, and test-command-validity doctor checks.

Project-state HCs (lookup, repo, gh-token, worktrees, deploy-flows, health,
gh-secrets, vps-reachable) live in test_doctor_project_full.py.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import patch

from yoke_core.engines.doctor import (
    DoctorArgs,
    RecordCollector,
    hc_approval_contract_drift,
    hc_api_vocabulary_drift,
    hc_browser_substrate,
    hc_session_startup_hook,
    hc_test_command_validity,
)
from runtime.api.fixtures.file_test_db import connect_test_db, init_test_db
from runtime.api.fixtures.machine_config_test import (
    clear_machine_checkout,
    register_machine_checkout,
)
from runtime.api.fixtures.schema_ddl import apply_fixture_ddl


def _make_conn() -> Any:
    """Disposable Postgres test DB; dropped when the conn is closed or GC'd."""
    from runtime.api.fixtures import pg_testdb

    name = pg_testdb.create_test_database()
    conn = pg_testdb.drop_database_on_close(
        pg_testdb.connect_test_database(name), name,
    )
    apply_fixture_ddl(
        conn,
        """
        CREATE TABLE projects (
            id INTEGER PRIMARY KEY,
            slug TEXT UNIQUE NOT NULL,
            name TEXT,
            github_repo TEXT,
            public_item_prefix TEXT DEFAULT 'YOK'
        );

        CREATE TABLE project_capabilities (
            id INTEGER PRIMARY KEY,
            project_id INTEGER,
            type TEXT,
            config TEXT
        );

        CREATE TABLE deployment_flows (
            id TEXT PRIMARY KEY,
            project_id INTEGER,
            stages TEXT
        );
        """
    )
    return conn


def _args(**overrides) -> DoctorArgs:
    defaults = dict(file=None, fix=False, only=None, quick=False, project="externalwebapp", db_path=None)
    defaults.update(overrides)
    return DoctorArgs(**defaults)


def _run_hc(fn, conn=None, **kwargs) -> RecordCollector:
    if conn is None:
        conn = _make_conn()
    rec = RecordCollector()
    fn(conn, _args(**kwargs), rec)
    return rec


class TestSessionStartupHook:
    def test_warns_when_settings_missing(self, tmp_path):
        with patch("yoke_core.engines.doctor_report._resolve_repo_root", return_value=str(tmp_path)):
            rec = _run_hc(hc_session_startup_hook, project="yoke")
        assert rec.results[0].result == "WARN"

    def test_warns_on_invalid_json(self, tmp_path):
        settings_dir = tmp_path / ".claude"
        settings_dir.mkdir()
        (settings_dir / "settings.json").write_text("{bad")
        with patch("yoke_core.engines.doctor_report._resolve_repo_root", return_value=str(tmp_path)):
            rec = _run_hc(hc_session_startup_hook, project="yoke")
        assert rec.results[0].result == "WARN"

    def test_passes_when_hook_cli_user_prompt_present(self, tmp_path):
        settings_dir = tmp_path / ".claude"
        settings_dir.mkdir()
        (settings_dir / "settings.json").write_text(
            json.dumps(
                {
                    "hooks": {
                        "UserPromptSubmit": [
                            {
                                "hooks": [
                                    {
                                        "command": (
                                            "yoke hook evaluate UserPromptSubmit"
                                        ),
                                    },
                                ],
                            },
                        ],
                    },
                },
            ),
        )
        with patch("yoke_core.engines.doctor_report._resolve_repo_root", return_value=str(tmp_path)):
            rec = _run_hc(hc_session_startup_hook, project="yoke")
        assert rec.results[0].result == "PASS"

    def test_warns_when_user_prompt_command_does_not_match_hook_cli(self, tmp_path):
        settings_dir = tmp_path / ".claude"
        settings_dir.mkdir()
        (settings_dir / "settings.json").write_text(
            json.dumps(
                {
                    "hooks": {
                        "UserPromptSubmit": [
                            {"hooks": [{"command": "echo not-the-runner"}]},
                        ],
                    },
                },
            ),
        )
        with patch("yoke_core.engines.doctor_report._resolve_repo_root", return_value=str(tmp_path)):
            rec = _run_hc(hc_session_startup_hook, project="yoke")
        assert rec.results[0].result == "WARN"
        assert "yoke hook evaluate owner" in rec.results[0].detail

    def test_passes_against_production_settings_json(self):
        """End-to-end: HC must PASS against the actual rendered .claude/settings.json.

        The engines-level autouse fixture isolates tests from the live
        repo root; this test deliberately reaches for the real
        ``.claude/settings.json`` so it temporarily restores the real
        resolver by calling out to ``git rev-parse``.
        """
        import subprocess
        real_root = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            capture_output=True, text=True, check=False,
        ).stdout.strip()
        assert real_root, "git rev-parse --show-toplevel returned empty"
        with patch(
            "yoke_core.engines.doctor_report._resolve_repo_root",
            return_value=real_root,
        ):
            rec = _run_hc(hc_session_startup_hook, project="yoke")
        assert rec.results[0].result == "PASS", rec.results[0].detail


class TestBrowserSubstrate:
    def test_warns_when_runtime_dir_missing(self, tmp_path):
        with patch(
            "yoke_core.domain.browser_runtime_home.runtime_dir",
            return_value=tmp_path / "browser-runtime",
        ):
            rec = _run_hc(hc_browser_substrate, project="yoke")
        assert rec.results[0].result == "WARN"
        assert "not materialized" in rec.results[0].detail

    def test_warns_when_dependencies_missing(self, tmp_path):
        browser_dir = tmp_path / "browser-runtime"
        browser_dir.mkdir(parents=True)
        with patch(
            "yoke_core.domain.browser_runtime_home.runtime_dir", return_value=browser_dir
        ):
            rec = _run_hc(hc_browser_substrate, project="yoke")
        assert rec.results[0].result == "WARN"
        assert "package.json" in rec.results[0].detail

    def test_passes_when_chromium_exists(self, tmp_path):
        browser_dir = tmp_path / "browser-runtime"
        browser_dir.mkdir(parents=True)
        (browser_dir / "package.json").write_text("{}")
        (browser_dir / "node_modules").mkdir()
        chromium = tmp_path / "chromium"
        chromium.write_text("bin")
        with patch(
            "yoke_core.domain.browser_runtime_home.runtime_dir", return_value=browser_dir
        ), patch(
            "yoke_core.engines.doctor_report._run"
        ) as run:
            run.return_value = type("CP", (), {"returncode": 0, "stdout": str(chromium)})()
            rec = _run_hc(hc_browser_substrate, project="yoke")
        assert rec.results[0].result == "PASS"


class TestLifecycleAndVocabulary:
    def test_api_vocabulary_drift_passes(self):
        rec = _run_hc(hc_api_vocabulary_drift, project="yoke")
        assert rec.results[0].result == "PASS"

    def test_approval_contract_drift_passes(self):
        rec = _run_hc(hc_approval_contract_drift, project="yoke")
        assert rec.results[0].result == "PASS"


def _apply_command_substrate_schema() -> None:
    """``apply_schema`` strategy: ``projects`` + ``project_structure``.

    Both the ``projects`` row (read from the passed conn) and the
    ``command_definitions`` family (read by the HC via ``list_commands`` through
    the factory) must co-locate on one DB. Building both through the backend
    factory plus the disposable per-test DB ``init_test_db`` provides gives that
    co-location AND isolation from other parallel workers — on Postgres the
    shared ambient DB would otherwise leak ``externalwebapp`` command rows between tests.
    """
    from yoke_core.domain import db_backend, project_structure as ps

    conn = db_backend.connect()
    try:
        apply_fixture_ddl(
            conn,
            """
            CREATE TABLE projects (
                id INTEGER PRIMARY KEY,
                slug TEXT UNIQUE NOT NULL,
                name TEXT,
                github_repo TEXT,
                public_item_prefix TEXT DEFAULT 'YOK'
            );
            """,
        )
        ps.create_project_structure_tables(conn)
        conn.commit()
    finally:
        conn.close()


class TestTestCommandValidity:
    """Tests read ``command_definitions`` via a disposable per-test DB so both
    the ``projects`` row and the ``project_structure`` the HC reads co-locate
    and stay isolated from other workers (on Postgres the shared ambient DB
    would otherwise leak command rows between tests)."""

    def _run(self, tmp_path, checkout_path, *, remove_checkout=False, **scopes):
        """Build a disposable DB (projects + command_definitions), run the HC,
        return the first result."""
        from yoke_core.domain import project_structure as ps

        ops = [
            {"op": "put", "family": "command_definitions",
             "attachment": "project", "entry_key": scope,
             "payload": {"command": command}}
            for scope, command in scopes.items() if command
        ]
        with init_test_db(
            tmp_path, apply_schema=_apply_command_substrate_schema
        ) as db_path:
            seed = connect_test_db(db_path)
            try:
                seed.execute(
                    "INSERT INTO projects "
                    "(id, slug, name, public_item_prefix) "
                    "VALUES (2, 'externalwebapp', 'ExternalWebapp', 'EXT')",
                )
                seed.commit()
            finally:
                seed.close()
            if checkout_path:
                checkout = Path(checkout_path)
                if checkout.is_dir():
                    register_machine_checkout(checkout.parent, checkout, 2)
                    if remove_checkout:
                        checkout.rmdir()
                else:
                    clear_machine_checkout(2)
            else:
                clear_machine_checkout(2)
            if ops:
                ps.apply_patch("externalwebapp", ops=ops, db_path=db_path)
            conn = connect_test_db(db_path)
            try:
                return _run_hc(hc_test_command_validity, conn,
                               project="yoke", db_path=db_path).results[0]
            finally:
                conn.close()

    def test_passes_when_project_commands_all_resolve(self, tmp_path):
        repo_path = tmp_path / "repo"
        repo_path.mkdir()
        (repo_path / "package.json").write_text('{"name":"externalwebapp"}\n')
        e2e_script = repo_path / "e2e.sh"
        e2e_script.write_text("#!/usr/bin/env sh\necho test\n")
        e2e_script.chmod(0o755)
        result = self._run(tmp_path, str(repo_path),
                           quick="python3 -m pytest -q",
                           full="npm test", e2e="sh e2e.sh")
        assert result.result == "PASS"

    def test_passes_when_no_commands_configured(self, tmp_path):
        repo_path = tmp_path / "repo"
        repo_path.mkdir()
        result = self._run(tmp_path, str(repo_path))
        assert result.result == "PASS"

    def test_warns_when_script_missing(self, tmp_path):
        repo_path = tmp_path / "repo"
        repo_path.mkdir()
        result = self._run(tmp_path, str(repo_path),
                           quick="sh scripts/does-not-exist.sh")
        assert result.result == "WARN"
        assert "externalwebapp.quick" in result.detail
        assert "does-not-exist.sh" in result.detail

    def test_warns_when_npm_has_no_package_json(self, tmp_path):
        repo_path = tmp_path / "repo"
        repo_path.mkdir()
        result = self._run(tmp_path, str(repo_path),
                           e2e="npm run test:browser")
        assert result.result == "WARN"
        assert "package.json" in result.detail

    def test_warns_when_checkout_mapping_is_missing(self, tmp_path):
        result = self._run(tmp_path, "", quick="sh scripts/run.sh")
        assert result.result == "WARN"
        assert "no machine-local checkout mapping" in result.detail

    def test_warns_when_mapped_checkout_is_not_a_directory(self, tmp_path):
        bogus_path = tmp_path / "does-not-exist"
        bogus_path.mkdir()
        result = self._run(
            tmp_path, str(bogus_path), remove_checkout=True,
            quick="sh scripts/run.sh",
        )
        assert result.result == "WARN"
