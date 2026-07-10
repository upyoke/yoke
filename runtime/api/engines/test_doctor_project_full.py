"""Tests for project-state doctor health checks (lookup, repo, worktrees,
deploy-flows, health, vps-reachable).

Canonical-resolver fixtures for GitHub auth live in
``test_doctor_project_full_canonical_auth.py``. Substrate and
test-command-validity HCs live in ``test_doctor_project_full_substrate.py``.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import patch

from yoke_core.engines.doctor import (
    DoctorArgs,
    RecordCollector,
    hc_project_deploy_flows,
    hc_project_health,
    hc_project_lookup,
    hc_project_repo_exists,
    hc_project_vps_reachable,
    hc_project_worktrees,
)
from runtime.api.fixtures.machine_config_test import (
    clear_machine_checkout,
    register_machine_checkout,
)


def _make_conn() -> Any:
    """Disposable Postgres test DB; dropped when the conn is closed or GC'd."""
    from runtime.api.fixtures import pg_testdb
    from runtime.api.fixtures.schema_ddl import apply_fixture_ddl

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
            settings TEXT,
            created_at TEXT
        );

        CREATE TABLE deployment_flows (
            id TEXT PRIMARY KEY,
            project_id INTEGER,
            stages TEXT
        );
        """
    )
    return conn


def _project_id(project: str) -> int:
    return {"yoke": 1, "buzz": 2}.get(project, 99)


def _seed_project(
    conn: Any,
    project: str,
    checkout_path: str | None = None,
    github_repo: str | None = None,
) -> None:
    project_id = _project_id(project)
    if checkout_path and Path(checkout_path).is_dir():
        checkout = Path(checkout_path)
        register_machine_checkout(checkout.parent, checkout, project_id)
    else:
        clear_machine_checkout(project_id)
    conn.execute(
        "INSERT INTO projects "
        "(id, slug, name, github_repo, public_item_prefix) "
        "VALUES (%s, %s, %s, %s, 'YOK') "
        "ON CONFLICT(id) DO NOTHING",
        (project_id, project, project.title(), github_repo),
    )


def _seed_capability(
    conn: Any,
    project: str,
    cap_type: str,
    settings: str,
) -> None:
    _seed_project(conn, project)
    conn.execute(
        "INSERT INTO project_capabilities (project_id, type, settings) "
        "VALUES (%s, %s, %s)",
        (_project_id(project), cap_type, settings),
    )


def _args(**overrides) -> DoctorArgs:
    defaults = dict(file=None, fix=False, only=None, quick=False, project="buzz", db_path=None)
    defaults.update(overrides)
    return DoctorArgs(**defaults)


def _run_hc(fn, conn=None, **kwargs) -> RecordCollector:
    if conn is None:
        conn = _make_conn()
    rec = RecordCollector()
    fn(conn, _args(**kwargs), rec)
    return rec


class TestProjectLookup:
    def test_warns_when_project_missing(self):
        rec = _run_hc(hc_project_lookup)
        assert rec.results[0].result == "WARN"
        assert "not found" in rec.results[0].detail

    def test_found_project_emits_no_record(self):
        conn = _make_conn()
        _seed_project(conn, "buzz")
        rec = _run_hc(hc_project_lookup, conn)
        assert rec.results == []

    def test_runs_for_yoke(self):
        """Post-seed, Yoke is a first-class project and the HC runs."""
        conn = _make_conn()
        _seed_project(conn, "yoke")
        rec = _run_hc(hc_project_lookup, conn, project="yoke")
        assert rec.results == []  # found, no record


class TestProjectRepoExists:
    def test_passes_when_repo_exists(self, tmp_path):
        conn = _make_conn()
        repo_path = tmp_path / "buzz-repo"
        repo_path.mkdir()
        _seed_project(conn, "buzz", checkout_path=str(repo_path))
        rec = _run_hc(hc_project_repo_exists, conn)
        assert rec.results[0].result == "PASS"

    def test_fails_when_repo_missing(self, tmp_path):
        conn = _make_conn()
        missing = tmp_path / "missing-repo"
        missing.mkdir(exist_ok=True)
        _seed_project(conn, "buzz", checkout_path=str(missing))
        missing.rmdir()
        rec = _run_hc(hc_project_repo_exists, conn)
        assert rec.results[0].result == "FAIL"

    def test_runs_for_yoke(self, tmp_path):
        conn = _make_conn()
        repo_path = tmp_path / "yoke-repo"
        repo_path.mkdir()
        _seed_project(conn, "yoke", checkout_path=str(repo_path))
        rec = _run_hc(hc_project_repo_exists, conn, project="yoke")
        assert rec.results[0].result == "PASS"


class TestProjectWorktrees:
    def test_warns_when_checkout_mapping_missing(self):
        conn = _make_conn()
        _seed_project(conn, "buzz")
        rec = _run_hc(hc_project_worktrees, conn)
        assert rec.results[0].result == "WARN"
        assert "no machine-local checkout mapping" in rec.results[0].detail

    def test_warns_on_stale_worktree(self, tmp_path):
        conn = _make_conn()
        repo_path = tmp_path / "repo"
        repo_path.mkdir()
        _seed_project(conn, "buzz", checkout_path=str(repo_path))
        output = f"worktree {tmp_path / 'missing-wt'}\n"
        with patch("yoke_core.engines.doctor_report._run") as run:
            run.return_value = type("CP", (), {"stdout": output})()
            rec = _run_hc(hc_project_worktrees, conn)
        assert rec.results[0].result == "WARN"
        assert "missing on disk" in rec.results[0].detail

    def test_passes_when_all_worktrees_exist(self, tmp_path):
        conn = _make_conn()
        repo_path = tmp_path / "repo"
        repo_path.mkdir()
        wt_path = tmp_path / "wt"
        wt_path.mkdir()
        _seed_project(conn, "buzz", checkout_path=str(repo_path))
        output = f"worktree {wt_path}\n"
        with patch("yoke_core.engines.doctor_report._run") as run:
            run.return_value = type("CP", (), {"stdout": output})()
            rec = _run_hc(hc_project_worktrees, conn)
        assert rec.results[0].result == "PASS"

    def test_runs_for_yoke(self, tmp_path):
        conn = _make_conn()
        repo_path = tmp_path / "yoke-repo"
        repo_path.mkdir()
        _seed_project(conn, "yoke", checkout_path=str(repo_path))
        with patch("yoke_core.engines.doctor_report._run") as run:
            run.return_value = type("CP", (), {"stdout": ""})()
            rec = _run_hc(hc_project_worktrees, conn, project="yoke")
        assert rec.results[0].result == "PASS"


class TestProjectDeployFlows:
    def test_passes_with_flow_count(self):
        conn = _make_conn()
        _seed_project(conn, "buzz")
        conn.execute(
            "INSERT INTO deployment_flows (id, project_id, stages) "
            "VALUES ('f1', %s, '[]')",
            (_project_id("buzz"),),
        )
        rec = _run_hc(hc_project_deploy_flows, conn)
        assert rec.results[0].result == "PASS"
        assert "1 deployment flow" in rec.results[0].detail

    def test_passes_with_no_flows(self):
        conn = _make_conn()
        _seed_project(conn, "buzz")
        rec = _run_hc(hc_project_deploy_flows, conn)
        assert rec.results[0].result == "PASS"
        assert "No deployment flows" in rec.results[0].detail

    def test_runs_for_yoke(self):
        """Yoke has its own deployment flow (yoke-internal)."""
        conn = _make_conn()
        _seed_project(conn, "yoke")
        conn.execute(
            "INSERT INTO deployment_flows (id, project_id, stages) "
            "VALUES ('yoke-internal', %s, '[]')",
            (_project_id("yoke"),),
        )
        rec = _run_hc(hc_project_deploy_flows, conn, project="yoke")
        assert rec.results[0].result == "PASS"
        assert "yoke" in rec.results[0].detail


class TestProjectHealth:
    def test_warns_on_invalid_json(self):
        conn = _make_conn()
        _seed_capability(conn, "buzz", "health-endpoint", "{bad}")
        rec = _run_hc(hc_project_health, conn)
        assert rec.results[0].result == "WARN"
        assert "invalid JSON" in rec.results[0].detail

    def test_warns_when_url_missing(self):
        conn = _make_conn()
        _seed_capability(
            conn,
            "buzz",
            "health-endpoint",
            json.dumps({"path": "/health"}),
        )
        rec = _run_hc(hc_project_health, conn)
        assert rec.results[0].result == "WARN"
        assert "no url" in rec.results[0].detail

    def test_passes_on_http_200(self):
        conn = _make_conn()
        _seed_capability(
            conn,
            "buzz",
            "health-endpoint",
            json.dumps({"url": "https://example.com/health"}),
        )
        with patch("yoke_core.engines.doctor_report._run") as run:
            run.return_value = type("CP", (), {"returncode": 0, "stdout": "200"})()
            rec = _run_hc(hc_project_health, conn)
        assert rec.results[0].result == "PASS"

    def test_warns_on_non_200(self):
        conn = _make_conn()
        _seed_capability(
            conn,
            "buzz",
            "health-endpoint",
            json.dumps({"url": "https://example.com/health"}),
        )
        with patch("yoke_core.engines.doctor_report._run") as run:
            run.return_value = type("CP", (), {"returncode": 1, "stdout": "000"})()
            rec = _run_hc(hc_project_health, conn)
        assert rec.results[0].result == "WARN"

    def test_skipped_for_yoke_intentional(self):
        """Yoke has no health-endpoint capability; Yoke-skip preserved
        with inline rationale comment in the HC source."""
        from yoke_core.engines import doctor_hc_worktrees_gh_project as mod
        import inspect
        src = inspect.getsource(mod.hc_project_health)
        assert "intentionally skipped" in src
        rec = _run_hc(hc_project_health, project="yoke")
        assert rec.results == []  # no record produced


class TestProjectVpsReachable:
    def test_warns_when_host_missing(self):
        conn = _make_conn()
        _seed_capability(conn, "buzz", "vps-ssh", json.dumps({"user": "ubuntu"}))
        rec = _run_hc(hc_project_vps_reachable, conn)
        assert rec.results[0].result == "WARN"

    def test_passes_when_ssh_succeeds(self):
        conn = _make_conn()
        _seed_capability(
            conn,
            "buzz",
            "vps-ssh",
            json.dumps({"host": "example.com"}),
        )
        with patch("yoke_core.engines.doctor_report._run") as run:
            run.return_value = type("CP", (), {"returncode": 0})()
            rec = _run_hc(hc_project_vps_reachable, conn)
        assert rec.results[0].result == "PASS"

    def test_warns_when_ssh_fails(self):
        conn = _make_conn()
        _seed_capability(
            conn,
            "buzz",
            "vps-ssh",
            json.dumps({"host": "example.com"}),
        )
        with patch("yoke_core.engines.doctor_report._run") as run:
            run.return_value = type("CP", (), {"returncode": 1})()
            rec = _run_hc(hc_project_vps_reachable, conn)
        assert rec.results[0].result == "WARN"

    def test_skipped_for_yoke_intentional(self):
        """Yoke has no VPS; Yoke-skip preserved with inline rationale."""
        from yoke_core.engines import doctor_hc_worktrees_gh_project as mod
        import inspect
        src = inspect.getsource(mod.hc_project_vps_reachable)
        assert "intentionally skipped" in src
        rec = _run_hc(hc_project_vps_reachable, project="yoke")
        assert rec.results == []  # no record produced
