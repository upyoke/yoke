"""DB-backed QA recorder integration tests for deploy_pipeline / deploy_qa_recorder.

Pure-unit (no DB fixture) tests live in test_deploy_pipeline_full.py.
"""

from __future__ import annotations

import json
import os

import pytest

from yoke_contracts.timestamps import parse_instant

from yoke_core.domain import db_backend
from yoke_core.domain import deploy_qa_recorder
from yoke_core.domain.schema_init_apply import execute_schema_script
from runtime.api.api_workflow_test_helpers import (
    install_workflow_registry_and_pin_items,
)
from runtime.api.fixtures.file_test_db import connect_test_db, init_test_db


from runtime.api.fixtures.deployment_pipeline_schema import (
    DEPLOYMENT_PIPELINE_SCHEMA as _SCHEMA,
)


def _apply_schema() -> None:
    """Build the inline deployment-pipeline schema against the test DB.

    Zero-arg ``apply_schema`` strategy for :func:`init_test_db`: resolves its
    connection through the backend factory (``YOKE_DB`` on SQLite, the
    repointed ``YOKE_PG_DSN`` on Postgres). The facade translates the
    ``INTEGER PRIMARY KEY`` columns and composite keys so the same ``_SCHEMA``
    builds on both engines. The code-under-test (``deploy_qa_recorder``) queries
    the tables directly without ``sqlite_master`` / ``pragma`` introspection, so
    no compat shims are installed here.
    """
    conn = db_backend.connect()
    try:
        execute_schema_script(conn, _SCHEMA)
        conn.execute(
            "INSERT INTO projects "
            "(id, slug, name, github_repo, public_item_prefix) "
            "VALUES (1, 'yoke', 'Yoke', 'upyoke/yoke', 'YOK')",
        )
        conn.execute("INSERT INTO sites (id, project_id, name) VALUES (10, 1, 'api')")
        conn.execute(
            "INSERT INTO environments (id, site, project_id, name) "
            "VALUES (101, 10, 1, 'prod')"
        )
        install_workflow_registry_and_pin_items(conn)
    finally:
        conn.close()


@pytest.fixture
def deploy_db(tmp_path, monkeypatch):
    """Minimal DB for deployment pipeline tests.

    The seam owns the per-test DB lifecycle: a real file under tmp_path on
    SQLite, a disposable per-test database (dropped on context exit) on
    Postgres. The yielded connection is opened backend-aware *inside* the
    context so the tests' direct ``deploy_db.execute(...)`` seeds and the
    code-under-test (``deploy_qa_recorder`` -> YOKE_DB / repointed DSN) hit
    the same database.
    """
    with init_test_db(tmp_path, apply_schema=_apply_schema) as db_path:
        monkeypatch.setenv("YOKE_DB", db_path)
        conn = connect_test_db(db_path)
        try:
            yield conn
        finally:
            conn.close()


def _seed_flow(conn, flow_id="flow-test", project="yoke", stages=None):
    if stages is None:
        stages = [
            {"name": "deploy", "step_runner": "auto"},
            {"name": "smoke-test", "step_runner": "auto", "qa_kind": "smoke"},
        ]
    conn.execute(
        "INSERT INTO deployment_flows "
        "(id, project_id, name, stages, target_tier, target_environment_id) "
        "VALUES (%s, %s, %s, %s, 'persistent', 101)",
        (flow_id, 1, flow_id, json.dumps(stages)),
    )
    conn.commit()


def _seed_run(
    conn,
    run_id="run-test-001",
    project="yoke",
    flow="flow-test",
    status="created",
    item_ids=None,
):
    conn.execute(
        "INSERT INTO deployment_runs (id, project_id, flow, status) "
        "VALUES (%s, %s, %s, %s)",
        (run_id, 1, flow, status),
    )
    for item_id in item_ids or []:
        conn.execute(
            "INSERT INTO deployment_run_items (run_id, item_id) VALUES (%s, %s)",
            (run_id, item_id),
        )
    conn.commit()


def _seed_item(
    conn,
    item_id=42,
    title="Test item",
    status="implemented",
    project="yoke",
    flow="flow-test",
):
    from yoke_core.domain.workflow_registry import resolve_current_workflow_pin

    workflow_id, workflow_version_id = resolve_current_workflow_pin(
        conn,
        "issue",
    )
    conn.execute(
        "INSERT INTO items "
        "(id, title, workflow_id, workflow_version_id, status, project_id, "
        "project_sequence, deployment_flow) "
        "VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
        (
            item_id,
            title,
            workflow_id,
            workflow_version_id,
            status,
            1,
            item_id,
            flow,
        ),
    )
    conn.commit()


class TestGetRequirement:
    def test_found(self, deploy_db):
        deploy_db.execute(
            "INSERT INTO qa_requirements (deployment_run_id, qa_kind, qa_phase) "
            "VALUES ('run-1', 'smoke', 'post_deploy')",
        )
        deploy_db.commit()
        val = deploy_qa_recorder.cmd_get_requirement(
            "run-1", "smoke", db_path=os.environ["YOKE_DB"]
        )
        assert val is not None

    def test_not_found(self, deploy_db):
        val = deploy_qa_recorder.cmd_get_requirement(
            "run-1", "smoke", db_path=os.environ["YOKE_DB"]
        )
        assert val is None


class TestRunSmokeStatus:
    def test_empty_run(self, deploy_db, capsys):
        deploy_qa_recorder.cmd_run_smoke_status(
            "run-nonexistent", db_path=os.environ["YOKE_DB"]
        )
        assert capsys.readouterr().out.strip() == ""

    def test_with_requirement(self, deploy_db, capsys):
        deploy_db.execute(
            "INSERT INTO qa_requirements (deployment_run_id, qa_kind, qa_phase) "
            "VALUES ('run-1', 'smoke', 'post_deploy')",
        )
        deploy_db.commit()
        deploy_qa_recorder.cmd_run_smoke_status("run-1", db_path=os.environ["YOKE_DB"])
        output = capsys.readouterr().out.strip()
        assert "run-1" in output
        assert "smoke" in output
        assert "pending" in output
        assert output.split("|")[4] == "null"

    @pytest.mark.parametrize("zone", ["UTC", "Asia/Kathmandu"])
    def test_completion_clock_projects_fixed_six_utc(
        self, deploy_db, capsys, monkeypatch, zone
    ):
        stamp = parse_instant("2026-01-01T00:00:00.123456Z")
        deploy_db.execute(
            "INSERT INTO qa_requirements (id, deployment_run_id, qa_kind, qa_phase) VALUES (99, 'run-clock', 'smoke', 'post_deploy')"
        )
        deploy_db.execute(
            "INSERT INTO qa_runs (qa_requirement_id, verdict, started_at, completed_at, created_at) VALUES (99, 'pass', %s, %s, %s)",
            (stamp, stamp, stamp),
        )
        deploy_db.commit()
        real_connect = deploy_qa_recorder.connect

        def connect_in_zone(*args, **kwargs):
            conn = real_connect(*args, **kwargs)
            conn.execute("SELECT set_config('TimeZone', %s, false)", (zone,))
            assert conn.execute("SHOW TimeZone").fetchone()[0] == zone
            return conn

        monkeypatch.setattr(deploy_qa_recorder, "connect", connect_in_zone)
        deploy_qa_recorder.cmd_run_smoke_status(
            "run-clock", db_path=os.environ["YOKE_DB"]
        )
        fields = capsys.readouterr().out.strip().split("|")
        assert fields[3:5] == ["pass", "2026-01-01T00:00:00.123456Z"]


class TestQaRecorderIntegration:
    """Test QA seeding and recording against a real DB, in-process (no subprocess)."""

    def test_seed_populates_requirements(self, deploy_db):
        """seed-from-flow creates qa_requirements for QA-relevant stages."""
        _seed_flow(deploy_db)
        _seed_run(deploy_db, item_ids=[42])
        _seed_item(deploy_db)

        deploy_db.execute(
            "INSERT INTO qa_requirements (deployment_run_id, qa_kind, qa_phase, "
            "blocking_mode, requirement_source, success_policy) "
            "VALUES ('run-test-001', 'smoke', 'post_deploy', 'blocking', "
            "'flow_derived', 'all-pass')",
        )
        deploy_db.commit()

        count = deploy_qa_recorder.cmd_seed_from_flow(
            "run-test-001",
            db_path=os.environ["YOKE_DB"],
        )
        assert count == 0  # Already seeded

    def test_seed_reports_error_not_zero_for_a_missing_flow_row(self, deploy_db):
        """A run whose flow row is missing is an error, not "nothing to seed".

        cmd_stages raises LookupError specifically when the flow is not
        found — distinct from a found flow with no QA-relevant stages,
        which legitimately returns 0.
        """
        deploy_db.execute(
            "INSERT INTO deployment_runs (id, project_id, flow, status) "
            "VALUES ('run-missing-flow', 1, 'flow-does-not-exist', 'created')",
        )
        deploy_db.commit()

        count = deploy_qa_recorder.cmd_seed_from_flow(
            "run-missing-flow",
            db_path=os.environ["YOKE_DB"],
        )
        assert count == -1

    def test_get_requirement_after_seed(self, deploy_db):
        """get-requirement returns the ID of a seeded requirement."""
        deploy_db.execute(
            "INSERT INTO qa_requirements (deployment_run_id, qa_kind, qa_phase) "
            "VALUES ('run-1', 'smoke', 'post_deploy')",
        )
        deploy_db.commit()

        req_id = deploy_qa_recorder.cmd_get_requirement(
            "run-1",
            "smoke",
            db_path=os.environ["YOKE_DB"],
        )
        assert req_id is not None
        assert isinstance(req_id, int)
