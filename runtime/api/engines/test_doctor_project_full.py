"""Tests for project-state doctor health checks (lookup, repo, worktrees,
deploy-flows, health). VPS reachability lives in
``test_doctor_project_vps_reachable.py``.

Canonical-resolver fixtures for GitHub auth live in
``test_doctor_project_full_canonical_auth.py``. Substrate and
test-command-validity HCs live in ``test_doctor_project_full_substrate.py``.
"""

from __future__ import annotations

from runtime.api.engines.doctor_project_full_test_support import (
    _args as _args,
    _make_conn as _make_conn,
    _project_id as _project_id,
    _run_hc as _run_hc,
    _seed_capability as _seed_capability,
    _seed_project as _seed_project,
)


import json
from unittest.mock import patch

from yoke_core.engines.doctor import (
    hc_project_deploy_flows,
    hc_project_health,
    hc_project_lookup,
    hc_project_repo_exists,
    hc_project_worktrees,
)


class TestProjectLookup:
    def test_warns_when_project_missing(self):
        rec = _run_hc(hc_project_lookup)
        assert rec.results[0].result == "WARN"
        assert "not found" in rec.results[0].detail

    def test_found_project_emits_no_record(self):
        conn = _make_conn()
        _seed_project(conn, "externalwebapp")
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
        repo_path = tmp_path / "externalwebapp-repo"
        repo_path.mkdir()
        _seed_project(conn, "externalwebapp", checkout_path=str(repo_path))
        rec = _run_hc(hc_project_repo_exists, conn)
        assert rec.results[0].result == "PASS"

    def test_fails_when_repo_missing(self, tmp_path):
        conn = _make_conn()
        missing = tmp_path / "missing-repo"
        missing.mkdir(exist_ok=True)
        _seed_project(conn, "externalwebapp", checkout_path=str(missing))
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
        _seed_project(conn, "externalwebapp")
        rec = _run_hc(hc_project_worktrees, conn)
        assert rec.results[0].result == "WARN"
        assert "no machine-local checkout mapping" in rec.results[0].detail

    def test_warns_on_stale_worktree(self, tmp_path):
        conn = _make_conn()
        repo_path = tmp_path / "repo"
        repo_path.mkdir()
        _seed_project(conn, "externalwebapp", checkout_path=str(repo_path))
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
        _seed_project(conn, "externalwebapp", checkout_path=str(repo_path))
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
        _seed_project(conn, "externalwebapp")
        conn.execute(
            "INSERT INTO deployment_flows (id, project_id, stages) "
            "VALUES ('f1', %s, '[]')",
            (_project_id("externalwebapp"),),
        )
        rec = _run_hc(hc_project_deploy_flows, conn)
        assert rec.results[0].result == "PASS"
        assert "1 deployment flow" in rec.results[0].detail

    def test_passes_with_no_flows(self):
        conn = _make_conn()
        _seed_project(conn, "externalwebapp")
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
        _seed_capability(conn, "externalwebapp", "health-endpoint", "{bad}")
        rec = _run_hc(hc_project_health, conn)
        assert rec.results[0].result == "WARN"
        assert "invalid JSON" in rec.results[0].detail

    def test_warns_when_url_missing(self):
        conn = _make_conn()
        _seed_capability(
            conn,
            "externalwebapp",
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
            "externalwebapp",
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
            "externalwebapp",
            "health-endpoint",
            json.dumps({"url": "https://example.com/health"}),
        )
        with patch("yoke_core.engines.doctor_report._run") as run:
            run.return_value = type("CP", (), {"returncode": 1, "stdout": "000"})()
            rec = _run_hc(hc_project_health, conn)
        assert rec.results[0].result == "WARN"

    def test_applicability_is_declared_not_branched_on_a_slug(self):
        """The installation's own project is excluded by declaration."""
        from yoke_core.engines.doctor_applicability import PROJECT_SCOPE_EXTERNAL
        from yoke_core.engines.doctor_applicability_declarations import (
            applicability_for,
        )

        shape = applicability_for("project-health")
        assert shape.project_scope == PROJECT_SCOPE_EXTERNAL
        assert shape.required_capabilities == ("health-endpoint",)


def test_remote_cleanup_needs_source_without_changing_worktree_scope():
    from yoke_core.engines.doctor_applicability import PROJECT_SCOPE_EXTERNAL
    from yoke_core.engines.doctor_applicability_declarations import applicability_for

    assert applicability_for("stale-remote-branches").requires_source_checkout
    worktrees = applicability_for("project-worktrees")
    assert worktrees.requires_source_checkout
    assert worktrees.project_scope == PROJECT_SCOPE_EXTERNAL
