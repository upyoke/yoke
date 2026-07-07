"""Doctor HC tests (Prompt/doc/schema HCs + orphan project/event HCs).

Other doctor_hc_meta_full tests live in sibling files.

Schema scaffolding shared via _doctor_hc_meta_full_test_helpers (private module).
Uses disposable Postgres test databases and mock subprocess for deterministic testing.
"""

from __future__ import annotations

import json
import re
import subprocess
import textwrap
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from yoke_core.engines.doctor import (
    DoctorArgs,
    RecordCollector,
    hc_doc_drift,
    hc_doc_health,
    hc_flow_stage_json,
    hc_invalid_item_flows,
    hc_orphaned_project_items,
    hc_projects_config_alignment,
    hc_prompt_command_consistency,
    hc_prompt_doctrine_consistency,
    hc_schema_drift,
    hc_schema_script_sync,
)

from yoke_core.engines._doctor_hc_meta_full_test_helpers import (
    _NOW_ISO,
    _args,
    _completed,
    _insert_deployment_flow,
    _insert_item,
    _iso_days_ago,
    _iso_minutes_ago,
    _make_conn,
    _result,
    _results,
    _run_hc,
    _seed_project,
)


class TestPromptCommandConsistency:
    """Tests for hc_prompt_command_consistency."""

    @patch("yoke_core.engines.doctor_report._resolve_repo_root", return_value=None)
    def test_pass_no_root(self, mock_root):
        rec = _run_hc(hc_prompt_command_consistency)
        assert _result(rec).result == "PASS"

    def test_detects_stale_browser_qa_run_scenario(self, tmp_path):
        """catch stale browser_qa run-scenario in prompt surfaces."""
        skill_dir = tmp_path / ".agents" / "skills" / "yoke" / "advance"
        skill_dir.mkdir(parents=True)
        (skill_dir / "browser-qa.md").write_text(
            "python3 -m yoke_core.domain.browser_qa run-scenario --item-id 42"
        )
        with patch("yoke_core.engines.doctor_report._resolve_repo_root",
                    return_value=str(tmp_path)):
            rec = _run_hc(hc_prompt_command_consistency)
        r = _result(rec)
        assert r.result == "FAIL"
        assert "browser_qa run-scenario" in r.detail

    def test_detects_stale_browser_client_resolve_cache(self, tmp_path):
        """catch stale browser_client resolve-cache in prompt surfaces."""
        skill_dir = tmp_path / ".agents" / "skills" / "yoke" / "advance"
        skill_dir.mkdir(parents=True)
        (skill_dir / "project-e2e.md").write_text(
            "python3 -m yoke_core.domain.browser_client resolve-cache proj dir"
        )
        with patch("yoke_core.engines.doctor_report._resolve_repo_root",
                    return_value=str(tmp_path)):
            rec = _run_hc(hc_prompt_command_consistency)
        r = _result(rec)
        assert r.result == "FAIL"
        assert "browser_client resolve-cache" in r.detail

    def test_detects_stale_snapshot_screenshot_url_flag(self, tmp_path):
        """catch stale snapshot screenshot --url usage in prompt surfaces."""
        skill_dir = tmp_path / ".agents" / "skills" / "yoke" / "advance"
        skill_dir.mkdir(parents=True)
        (skill_dir / "browser-qa.md").write_text(
            "python3 -m yoke_core.domain.browser_client snapshot screenshot --url https://example.test"
        )
        with patch("yoke_core.engines.doctor_report._resolve_repo_root",
                    return_value=str(tmp_path)):
            rec = _run_hc(hc_prompt_command_consistency)
        r = _result(rec)
        assert r.result == "FAIL"
        assert "snapshot screenshot --url" in r.detail

    def test_pass_clean_surfaces(self, tmp_path):
        """clean prompt surfaces pass the check."""
        skill_dir = tmp_path / ".agents" / "skills" / "yoke" / "advance"
        skill_dir.mkdir(parents=True)
        (skill_dir / "browser-qa.md").write_text(
            "python3 -m yoke_core.domain.browser_qa --item-id 42"
        )
        agent_dir = tmp_path / "runtime" / "agents"
        agent_dir.mkdir(parents=True)
        (agent_dir / "tester.md").write_text(
            "python3 -m yoke_core.domain.browser_qa --item-id 42"
        )
        with patch("yoke_core.engines.doctor_report._resolve_repo_root",
                    return_value=str(tmp_path)):
            rec = _run_hc(hc_prompt_command_consistency)
        assert _result(rec).result == "PASS"


class TestPromptDoctrineConsistency:
    """Tests for hc_prompt_doctrine_consistency."""

    @patch("yoke_core.engines.doctor_report._resolve_repo_root", return_value=None)
    def test_pass_no_root(self, mock_root):
        rec = _run_hc(hc_prompt_doctrine_consistency)
        assert _result(rec).result == "PASS"


class TestDocHealth:
    """Tests for hc_doc_health."""

    @patch("yoke_core.engines.doctor_report._resolve_repo_root", return_value=None)
    def test_pass_no_root(self, mock_root):
        """Pass when no repo root found."""
        rec = _run_hc(hc_doc_health)
        assert _result(rec).result == "PASS"

    @patch("yoke_core.engines.doctor_report._resolve_repo_root", return_value="/fake/repo")
    def test_missing_readme_fails(self, mock_root):
        """T1: Missing README.md triggers FAIL."""
        with patch.object(Path, "is_file", return_value=False), \
             patch.object(Path, "is_dir", return_value=False):
            rec = _run_hc(hc_doc_health)
        assert _result(rec).result == "FAIL"
        assert "missing" in _result(rec).detail


class TestDocDrift:
    """Tests for hc_doc_drift."""

    @patch("yoke_core.engines.doctor_report._resolve_repo_root", return_value=None)
    def test_pass_no_root(self, mock_root):
        rec = _run_hc(hc_doc_drift)
        assert _result(rec).result == "PASS"


class TestSchemaDrift:
    """Tests for hc_schema_drift."""

    def test_schema_drift_on_minimal_db(self):
        """On a minimal test schema, should at least run without error."""
        conn = _make_conn()
        rec = _run_hc(hc_schema_drift, conn)
        res = _results(rec)
        assert res["HC-schema-drift"][0] in ("PASS", "WARN")


class TestSchemaScriptSync:
    """Tests for hc_schema_script_sync."""

    @patch("yoke_core.engines.doctor_report._resolve_repo_root", return_value=None)
    def test_pass_no_root(self, mock_root):
        """Pass when no repo root found."""
        conn = _make_conn()
        rec = _run_hc(hc_schema_script_sync, conn)
        assert _result(rec).result == "PASS"


class TestOrphanedProjectItems:
    """HC-orphaned-project-items: items referencing non-existent projects."""

    def test_pass_valid_project(self):
        conn = _make_conn()
        _seed_project(conn, "yoke")
        _insert_item(conn, 1)
        rec = _run_hc(hc_orphaned_project_items, conn)
        assert _result(rec).result == "PASS"

    def test_warn_orphan_project(self):
        conn = _make_conn()
        _seed_project(conn, "yoke")
        _insert_item(conn, 1, project="nonexistent")
        rec = _run_hc(hc_orphaned_project_items, conn)
        assert _result(rec).result == "WARN"


class TestFlowStageJsonMeta:
    """HC-flow-stage-json: flow stage JSON validity."""

    def test_pass_valid_json(self):
        conn = _make_conn()
        _insert_deployment_flow(conn, "f1", stages=json.dumps([{"name": "build"}]))
        rec = _run_hc(hc_flow_stage_json, conn)
        assert _result(rec).result == "PASS"

    def test_fail_invalid_json(self):
        conn = _make_conn()
        _insert_deployment_flow(conn, "f1", stages="not json {")
        rec = _run_hc(hc_flow_stage_json, conn)
        assert _result(rec).result == "FAIL"


class TestInvalidItemFlowsMeta:
    """HC-invalid-item-flows: items referencing non-existent flows."""

    def test_pass_valid_flow(self):
        conn = _make_conn()
        _insert_deployment_flow(conn, "f1")
        _insert_item(conn, 1, deployment_flow="f1")
        rec = _run_hc(hc_invalid_item_flows, conn)
        assert _result(rec).result == "PASS"

    def test_warn_nonexistent_flow(self):
        conn = _make_conn()
        _insert_item(conn, 1, deployment_flow="missing-flow")
        rec = _run_hc(hc_invalid_item_flows, conn)
        assert _result(rec).result == "WARN"


class TestProjectsConfigAlignment:
    """HC-projects-config-alignment: config file alignment."""

    def test_pass_no_projects(self):
        conn = _make_conn()
        rec = _run_hc(hc_projects_config_alignment, conn)
        # May PASS or WARN depending on config file presence
        assert _result(rec).result in ("PASS", "WARN")
