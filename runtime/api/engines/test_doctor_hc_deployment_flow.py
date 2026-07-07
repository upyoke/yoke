"""HC-invalid-item-flows: registered-alternatives suffix and --fix advisory."""

from __future__ import annotations

import json
from pathlib import Path

from yoke_core.engines.doctor import hc_flow_workflow_exists, hc_invalid_item_flows

from yoke_core.engines._doctor_hc_meta_full_test_helpers import (
    _insert_deployment_flow,
    _insert_item,
    _make_conn,
    _result,
    _run_hc,
    _seed_project,
)
from runtime.api.fixtures.machine_config_test import register_machine_checkout


def _seed_flow(conn, flow_id: str, project: str) -> None:
    _insert_deployment_flow(conn, flow_id, project=project)


def _seed_project_with_checkout(conn, project: str, checkout: str, config_root) -> None:
    _seed_project(conn, project)
    register_machine_checkout(
        Path(config_root),
        Path(checkout),
        2 if project == "buzz" else 1,
    )


def _seed_flow_with_stages(conn, flow_id: str, project: str, stages: object) -> None:
    _insert_deployment_flow(conn, flow_id, project=project, stages=json.dumps(stages))


class TestFlowWorkflowExists:
    def test_checks_project_repo_github_workflows(self, tmp_path, monkeypatch):
        conn = _make_conn()
        fallback = tmp_path / "yoke"
        fallback.mkdir()
        project_repo = tmp_path / "buzz"
        workflow = project_repo / ".github" / "workflows" / "buzz-deploy.yml"
        workflow.parent.mkdir(parents=True)
        workflow.write_text("name: deploy\n", encoding="utf-8")
        _seed_project_with_checkout(
            conn, "buzz", str(project_repo), tmp_path / "machine-config",
        )
        _seed_flow_with_stages(
            conn,
            "buzz-prod-release",
            "buzz",
            [{"name": "prod", "workflow": "buzz-deploy.yml"}],
        )
        monkeypatch.setattr(
            "yoke_core.engines.doctor_report._resolve_repo_root",
            lambda: str(fallback),
        )

        rec = _run_hc(hc_flow_workflow_exists, conn)
        result = _result(rec)

        assert result.result == "PASS"

    def test_missing_workflow_names_project_checkout(self, tmp_path, monkeypatch):
        conn = _make_conn()
        fallback = tmp_path / "yoke"
        fallback.mkdir()
        project_repo = tmp_path / "buzz"
        project_repo.mkdir()
        _seed_project_with_checkout(
            conn, "buzz", str(project_repo), tmp_path / "machine-config",
        )
        _seed_flow_with_stages(
            conn,
            "buzz-prod-release",
            "buzz",
            [{"name": "prod", "workflow": "buzz-deploy.yml"}],
        )
        monkeypatch.setattr(
            "yoke_core.engines.doctor_report._resolve_repo_root",
            lambda: str(fallback),
        )

        rec = _run_hc(hc_flow_workflow_exists, conn)
        result = _result(rec)

        assert result.result == "WARN"
        assert ".github/workflows/buzz-deploy.yml" in result.detail
        assert "projects/buzz/workflows" not in result.detail


class TestInvalidItemFlowsMessageEnhancements:
    def test_message_lists_registered_alternatives_for_no_project_item(self):
        conn = _make_conn()
        _seed_flow(conn, "yoke-internal", "yoke")
        _seed_flow(conn, "buzz-internal", "buzz")
        # Item has no project (explicit NULL) — show all registered flows.
        _insert_item(conn, 1, deployment_flow="garbage", project=None)
        rec = _run_hc(hc_invalid_item_flows, conn)
        result = _result(rec)
        assert result.result == "WARN"
        assert "garbage" in result.detail
        assert "is not registered" in result.detail
        assert "yoke-internal" in result.detail
        assert "buzz-internal" in result.detail
        # Operator-facing remediation hint.
        assert "repair by hand" in result.detail

    def test_message_filters_alternatives_by_item_project(self):
        conn = _make_conn()
        _seed_flow(conn, "yoke-internal", "yoke")
        _seed_flow(conn, "buzz-internal", "buzz")
        _insert_item(conn, 1, "Yoke item", deployment_flow="garbage")
        rec = _run_hc(hc_invalid_item_flows, conn)
        result = _result(rec)
        assert result.result == "WARN"
        assert "yoke-internal" in result.detail
        # Alternatives are project-filtered — buzz flows must not appear.
        assert "buzz-internal" not in result.detail
        assert "project 'yoke'" in result.detail

    def test_message_when_no_flows_for_project_falls_back_to_all(self):
        conn = _make_conn()
        _seed_flow(conn, "yoke-internal", "yoke")
        _seed_project(conn, "ghost-project")
        # Item references a project with no registered flows.
        _insert_item(conn, 1, "Orphan project", deployment_flow="garbage", project="ghost-project")
        rec = _run_hc(hc_invalid_item_flows, conn)
        result = _result(rec)
        assert result.result == "WARN"
        assert "no flows for project 'ghost-project'" in result.detail
        # Falls back to listing all registered flows since per-project list is empty.
        assert "yoke-internal" in result.detail

    def test_literal_none_string_repro(self):
        conn = _make_conn()
        _seed_flow(conn, "yoke-internal", "yoke")
        _insert_item(conn, 1, "Repro", deployment_flow="none")
        rec = _run_hc(hc_invalid_item_flows, conn)
        result = _result(rec)
        assert result.result == "WARN"
        assert "'none'" in result.detail
        assert "is not registered" in result.detail
