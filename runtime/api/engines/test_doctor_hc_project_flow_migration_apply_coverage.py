"""HC-project-flow-migration-apply-coverage: declared models need a flow stage.

Verifies the doctor HC catches the silent stuck-ticket class that
YOK-1882 surfaced live: a project declares a ``migration_model``
capability but no project flow carries a ``migration_apply`` stage
referencing that model at ``lifecycle_phase='implementing'``.
"""

from __future__ import annotations

import json

from yoke_core.domain import db_backend
from yoke_core.engines.doctor_hc_db_flows import (
    hc_project_flow_migration_apply_coverage,
)
from yoke_core.engines._doctor_hc_meta_full_test_helpers import (
    _make_conn,
    _result,
    _run_hc,
)


def _p(conn) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def _project_id(project: str) -> int:
    return {"yoke": 1, "externalwebapp": 2}[project]


def _seed_capability(conn, project: str, settings: dict) -> None:
    p = _p(conn)
    conn.execute(
        "INSERT INTO project_capabilities (project_id, type, settings) "
        f"VALUES ({p}, 'migration_model', {p})",
        (_project_id(project), json.dumps(settings)),
    )


def _seed_flow(conn, flow_id: str, project: str, stages: list) -> None:
    p = _p(conn)
    conn.execute(
        f"INSERT INTO deployment_flows (id, project_id, stages) VALUES ({p}, {p}, {p})",
        (flow_id, _project_id(project), json.dumps(stages)),
    )


def _model_settings(*model_names: str) -> dict:
    return {
        "models": {
            name: {
                "authoritative_db": {"kind": "sqlite_file",
                                      "location": {"path": "data/x.db"}},
                "runner": {"kind": "governed_migration_module",
                            "config": {"connection_env_var": "X_DB",
                                        "modules_dir": "migrations"}},
            }
            for name in model_names
        }
    }


def _migration_apply(model_name: str, phase: str = "implementing") -> dict:
    return {
        "kind": "migration_apply",
        "model_name": model_name,
        "lifecycle_phase": phase,
    }


class TestProjectFlowMigrationApplyCoverage:
    def test_no_capability_table_skips(self):
        conn = _make_conn()
        conn.execute("DROP TABLE project_capabilities")
        rec = _run_hc(hc_project_flow_migration_apply_coverage, conn)
        result = _result(rec)
        assert result.result == "PASS"
        assert "project_capabilities table does not exist" in result.detail

    def test_no_flows_table_skips(self):
        conn = _make_conn()
        conn.execute("DROP TABLE deployment_flows")
        rec = _run_hc(hc_project_flow_migration_apply_coverage, conn)
        result = _result(rec)
        assert result.result == "PASS"
        assert "deployment_flows table does not exist" in result.detail

    def test_no_migration_model_capability_passes(self):
        conn = _make_conn()
        # No migration_model rows at all.
        rec = _run_hc(hc_project_flow_migration_apply_coverage, conn)
        result = _result(rec)
        assert result.result == "PASS"
        assert "no projects declare" in result.detail

    def test_class_a_no_flow_stage_at_all_fails(self):
        """Class A: model declared, zero flows reference it."""
        conn = _make_conn()
        _seed_capability(conn, "externalwebapp", _model_settings("primary"))
        _seed_flow(conn, "externalwebapp-internal", "externalwebapp", [
            {"name": "merged", "executor": "auto"},
            {"name": "complete", "executor": "auto"},
        ])
        rec = _run_hc(hc_project_flow_migration_apply_coverage, conn)
        result = _result(rec)
        assert result.result == "FAIL"
        assert "project 'externalwebapp'" in result.detail
        assert "'primary'" in result.detail
        assert "no migration_apply stage" in result.detail
        assert "externalwebapp-internal" in result.detail

    def test_class_b_wrong_phase_fails(self):
        """Class B: stage exists but never at lifecycle_phase='implementing'."""
        conn = _make_conn()
        _seed_capability(conn, "externalwebapp", _model_settings("primary"))
        _seed_flow(conn, "externalwebapp-prod", "externalwebapp", [
            _migration_apply("primary", phase="reviewing-implementation"),
            {"name": "merged", "executor": "auto"},
        ])
        rec = _run_hc(hc_project_flow_migration_apply_coverage, conn)
        result = _result(rec)
        assert result.result == "FAIL"
        assert "never at lifecycle_phase='implementing'" in result.detail
        assert "reviewing-implementation" in result.detail
        assert "externalwebapp-prod" in result.detail

    def test_implementing_phase_passes(self):
        conn = _make_conn()
        _seed_capability(conn, "externalwebapp", _model_settings("primary"))
        _seed_flow(conn, "externalwebapp-prod", "externalwebapp", [
            _migration_apply("primary"),
            {"name": "merged", "executor": "auto"},
        ])
        rec = _run_hc(hc_project_flow_migration_apply_coverage, conn)
        result = _result(rec)
        assert result.result == "PASS"

    def test_any_flow_with_stage_satisfies_coverage(self):
        """Coverage requires ONE flow per model, not every flow."""
        conn = _make_conn()
        _seed_capability(conn, "externalwebapp", _model_settings("primary"))
        _seed_flow(conn, "externalwebapp-internal", "externalwebapp", [
            {"name": "merged", "executor": "auto"},
        ])
        _seed_flow(conn, "externalwebapp-prod", "externalwebapp", [
            _migration_apply("primary"),
            {"name": "merged", "executor": "auto"},
        ])
        rec = _run_hc(hc_project_flow_migration_apply_coverage, conn)
        result = _result(rec)
        assert result.result == "PASS"

    def test_per_model_independent(self):
        """Two declared models; one covered, one not. Issues only the uncovered."""
        conn = _make_conn()
        _seed_capability(conn, "externalwebapp", _model_settings("primary", "events"))
        _seed_flow(conn, "externalwebapp-prod", "externalwebapp", [
            _migration_apply("primary"),
        ])
        rec = _run_hc(hc_project_flow_migration_apply_coverage, conn)
        result = _result(rec)
        assert result.result == "FAIL"
        assert "'events'" in result.detail
        assert "no migration_apply stage" in result.detail
        # 'primary' is covered — must not appear as an issue.
        # The issues list mentions models individually; primary should be absent
        # from the FAIL detail. Stage absence text uses the model name in quotes.
        primary_complaint = "'primary' has no migration_apply"
        assert primary_complaint not in result.detail

    def test_multiple_projects_independent(self):
        conn = _make_conn()
        _seed_capability(conn, "yoke", _model_settings("primary"))
        _seed_capability(conn, "externalwebapp", _model_settings("primary"))
        _seed_flow(conn, "yoke-internal", "yoke", [
            _migration_apply("primary"),
        ])
        _seed_flow(conn, "externalwebapp-internal", "externalwebapp", [
            {"name": "merged", "executor": "auto"},
        ])
        rec = _run_hc(hc_project_flow_migration_apply_coverage, conn)
        result = _result(rec)
        assert result.result == "FAIL"
        # Only externalwebapp should be flagged.
        assert "project 'externalwebapp'" in result.detail
        assert "project 'yoke'" not in result.detail

    def test_malformed_capability_settings_fails_loudly(self):
        conn = _make_conn()
        conn.execute(
            "INSERT INTO project_capabilities (project_id, type, settings) "
            "VALUES (2, 'migration_model', '{not json')"
        )
        rec = _run_hc(hc_project_flow_migration_apply_coverage, conn)
        result = _result(rec)
        assert result.result == "FAIL"
        assert "malformed settings JSON" in result.detail

    def test_empty_models_dict_fails(self):
        conn = _make_conn()
        _seed_capability(conn, "externalwebapp", {"models": {}})
        rec = _run_hc(hc_project_flow_migration_apply_coverage, conn)
        result = _result(rec)
        assert result.result == "FAIL"
        assert "declares no models" in result.detail

    def test_remediation_hint_lists_project_flows(self):
        conn = _make_conn()
        _seed_capability(conn, "externalwebapp", _model_settings("primary"))
        _seed_flow(conn, "externalwebapp-prod-release", "externalwebapp", [
            {"name": "merged", "executor": "auto"},
        ])
        _seed_flow(conn, "externalwebapp-prod-hotfix", "externalwebapp", [
            {"name": "merged", "executor": "auto"},
        ])
        rec = _run_hc(hc_project_flow_migration_apply_coverage, conn)
        result = _result(rec)
        assert result.result == "FAIL"
        assert "externalwebapp-prod-release" in result.detail
        assert "externalwebapp-prod-hotfix" in result.detail
        assert "Add the stage to one of" in result.detail
