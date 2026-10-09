"""Tests for substrate, vocabulary, and test-command-validity doctor checks.

Project-state HCs (lookup, repo, gh-token, worktrees, deploy-flows, health,
gh-secrets, vps-reachable) live in test_doctor_project_full.py.
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import patch

from yoke_project_checks.check_agents import hc_browser_substrate
from yoke_project_checks.check_agents_hooks import hc_session_startup_hook
from yoke_project_checks.check_contract_drift import (
    hc_api_vocabulary_drift,
    hc_approval_contract_drift,
)
from yoke_core.engines.doctor import (
    DoctorArgs,
    RecordCollector,
)
from runtime.api.fixtures.schema_ddl import apply_fixture_ddl


def _make_conn() -> Any:
    """Disposable Postgres test DB; dropped when the conn is closed or GC'd."""
    from runtime.api.fixtures import pg_testdb

    name = pg_testdb.create_test_database()
    conn = pg_testdb.drop_database_on_close(
        pg_testdb.connect_test_database(name),
        name,
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
        """,
    )
    return conn


def _args(**overrides) -> DoctorArgs:
    defaults = dict(
        file=None,
        fix=False,
        only=None,
        quick=False,
        project="externalwebapp",
        db_path=None,
    )
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
        with patch(
            "yoke_core.engines.doctor_report._resolve_repo_root",
            return_value=str(tmp_path),
        ):
            rec = _run_hc(hc_session_startup_hook, project="yoke")
        assert rec.results[0].result == "WARN"

    def test_warns_on_invalid_json(self, tmp_path):
        settings_dir = tmp_path / ".claude"
        settings_dir.mkdir()
        (settings_dir / "settings.json").write_text("{bad")
        with patch(
            "yoke_core.engines.doctor_report._resolve_repo_root",
            return_value=str(tmp_path),
        ):
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
        with patch(
            "yoke_core.engines.doctor_report._resolve_repo_root",
            return_value=str(tmp_path),
        ):
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
        with patch(
            "yoke_core.engines.doctor_report._resolve_repo_root",
            return_value=str(tmp_path),
        ):
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
            capture_output=True,
            text=True,
            check=False,
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
            "yoke_harness.browser_runtime_home.runtime_dir",
            return_value=tmp_path / "browser-runtime",
        ):
            rec = _run_hc(hc_browser_substrate, project="yoke")
        assert rec.results[0].result == "WARN"
        assert "not materialized" in rec.results[0].detail

    def test_warns_when_dependencies_missing(self, tmp_path):
        browser_dir = tmp_path / "browser-runtime"
        browser_dir.mkdir(parents=True)
        with patch(
            "yoke_harness.browser_runtime_home.runtime_dir", return_value=browser_dir
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
        with (
            patch(
                "yoke_harness.browser_runtime_home.runtime_dir",
                return_value=browser_dir,
            ),
            patch("yoke_core.engines.doctor_report._run") as run,
        ):
            run.return_value = type(
                "CP", (), {"returncode": 0, "stdout": str(chromium)}
            )()
            rec = _run_hc(hc_browser_substrate, project="yoke")
        assert rec.results[0].result == "PASS"


class TestLifecycleAndVocabulary:
    def test_api_vocabulary_drift_passes(self):
        rec = _run_hc(hc_api_vocabulary_drift, project="yoke")
        assert rec.results[0].result == "PASS"

    def test_approval_contract_drift_passes(self):
        rec = _run_hc(hc_approval_contract_drift, project="yoke")
        assert rec.results[0].result == "PASS"
