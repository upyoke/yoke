"""DB-backed QA recorder integration tests for deploy_pipeline / deploy_qa_recorder.

Pure-unit (no DB fixture) tests live in test_deploy_pipeline_full.py.
"""

from __future__ import annotations

import json
import os

import pytest

from yoke_core.domain import db_backend
from yoke_core.domain import deploy_qa_recorder
from yoke_core.domain.schema_init_apply import execute_schema_script
from runtime.api.fixtures.file_test_db import connect_test_db, init_test_db


_SCHEMA = """
    CREATE TABLE items (
        id INTEGER PRIMARY KEY,
        title TEXT,
        type TEXT DEFAULT 'issue',
        status TEXT DEFAULT 'implemented',
        worktree TEXT,
        project_id INTEGER DEFAULT 1,
        project_sequence INTEGER NOT NULL,
        deployment_flow TEXT,
        deploy_stage TEXT,
        deployed_to TEXT,
        github_issue TEXT,
        frozen INTEGER DEFAULT 0
    );
    CREATE TABLE projects (
        id INTEGER PRIMARY KEY,
        slug TEXT UNIQUE,
        name TEXT,
        github_repo TEXT,
        default_branch TEXT DEFAULT 'main',
        public_item_prefix TEXT DEFAULT 'YOK'
    );
    CREATE TABLE deployment_flows (
        id TEXT PRIMARY KEY,
        project_id INTEGER,
        name TEXT,
        stages TEXT,
        target_env TEXT
    );
    CREATE TABLE deployment_runs (
        id TEXT PRIMARY KEY,
        project_id INTEGER,
        flow TEXT,
        target_env TEXT,
        release_lineage TEXT,
        status TEXT DEFAULT 'created',
        current_stage TEXT,
        created_at TEXT,
        started_at TEXT,
        completed_at TEXT,
        created_by TEXT DEFAULT 'operator'
    );
    CREATE TABLE deployment_run_items (
        run_id TEXT,
        item_id INTEGER,
        added_at TEXT,
        PRIMARY KEY (run_id, item_id)
    );
    CREATE TABLE deployment_run_qa (
        id INTEGER PRIMARY KEY,
        run_id TEXT,
        check_name TEXT,
        source TEXT DEFAULT 'flow_default',
        blocking INTEGER DEFAULT 1,
        status TEXT DEFAULT 'pending',
        updated_at TEXT,
        UNIQUE(run_id, check_name)
    );
    CREATE TABLE qa_requirements (
        id INTEGER PRIMARY KEY,
        item_id INTEGER,
        deployment_run_id TEXT,
        qa_kind TEXT,
        qa_phase TEXT,
        blocking_mode TEXT DEFAULT 'blocking',
        requirement_source TEXT,
        success_policy TEXT
    );
    CREATE TABLE qa_runs (
        id INTEGER PRIMARY KEY,
        qa_requirement_id INTEGER,
        executor_type TEXT,
        qa_kind TEXT,
        verdict TEXT,
        raw_result TEXT,
        completed_at TEXT,
        duration_ms INTEGER,
        created_at TEXT
    );
    CREATE TABLE qa_artifacts (
        id INTEGER PRIMARY KEY,
        qa_run_id INTEGER,
        artifact_type TEXT,
        content_type TEXT,
        metadata TEXT
    );
    CREATE TABLE events (
        id INTEGER PRIMARY KEY,
        event_name TEXT,
        event_type TEXT,
        source_type TEXT,
        created_at TEXT,
        envelope TEXT
    );
"""


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
        conn.commit()
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


def _seed_flow(conn, flow_id="flow-test", project="yoke", stages=None, target_env="production"):
    if stages is None:
        stages = [
            {"name": "deploy", "executor": "auto"},
            {"name": "smoke-test", "executor": "auto", "qa_kind": "smoke"},
        ]
    conn.execute(
        "INSERT INTO deployment_flows (id, project_id, name, stages, target_env) "
        "VALUES (%s, %s, %s, %s, %s)",
        (flow_id, 1, flow_id, json.dumps(stages), target_env),
    )
    conn.commit()


def _seed_run(conn, run_id="run-test-001", project="yoke", flow="flow-test",
              status="created", item_ids=None):
    conn.execute(
        "INSERT INTO deployment_runs (id, project_id, flow, status) "
        "VALUES (%s, %s, %s, %s)",
        (run_id, 1, flow, status),
    )
    for item_id in (item_ids or []):
        conn.execute(
            "INSERT INTO deployment_run_items (run_id, item_id) VALUES (%s, %s)",
            (run_id, item_id),
        )
    conn.commit()


def _seed_item(conn, item_id=42, title="Test item", status="implemented",
               project="yoke", flow="flow-test"):
    conn.execute(
        "INSERT INTO items (id, title, status, project_id, project_sequence, deployment_flow) "
        "VALUES (%s, %s, %s, %s, %s, %s)",
        (item_id, title, status, 1, item_id, flow),
    )
    conn.commit()


class TestGetRequirement:

    def test_found(self, deploy_db):
        deploy_db.execute(
            "INSERT INTO qa_requirements (deployment_run_id, qa_kind, qa_phase) "
            "VALUES ('run-1', 'smoke', 'post_deploy')",
        )
        deploy_db.commit()
        val = deploy_qa_recorder.cmd_get_requirement("run-1", "smoke", db_path=os.environ["YOKE_DB"])
        assert val is not None

    def test_not_found(self, deploy_db):
        val = deploy_qa_recorder.cmd_get_requirement("run-1", "smoke", db_path=os.environ["YOKE_DB"])
        assert val is None


class TestRunSmokeStatus:

    def test_empty_run(self, deploy_db, capsys):
        deploy_qa_recorder.cmd_run_smoke_status("run-nonexistent", db_path=os.environ["YOKE_DB"])
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


class TestQaRecorderIntegration:
    """Test QA seeding and recording with a real DB but mocked shell calls."""

    def test_seed_populates_requirements(self, deploy_db, monkeypatch):
        """seed-from-flow creates qa_requirements for QA-relevant stages."""
        _seed_flow(deploy_db)
        _seed_run(deploy_db, item_ids=[42])
        _seed_item(deploy_db)

        def mock_yoke_db(*args, script_dir=None):
            if "runs" in args and "get" in args and "flow" in args:
                return "flow-test"
            return ""

        def mock_flow_db(*args, script_dir=None):
            if "stages" in args:
                return json.dumps([
                    {"name": "deploy", "executor": "auto"},
                    {"name": "smoke-test", "executor": "auto", "qa_kind": "smoke"},
                ])
            return ""

        monkeypatch.setattr(deploy_qa_recorder, "_dispatch_db_router", mock_yoke_db)
        monkeypatch.setattr(deploy_qa_recorder, "_dispatch_flow_domain", mock_flow_db)

        deploy_db.execute(
            "INSERT INTO qa_requirements (deployment_run_id, qa_kind, qa_phase, "
            "blocking_mode, requirement_source, success_policy) "
            "VALUES ('run-test-001', 'smoke', 'post_deploy', 'blocking', "
            "'flow_derived', 'Workflow completes with conclusion=success')",
        )
        deploy_db.commit()

        count = deploy_qa_recorder.cmd_seed_from_flow(
            "run-test-001",
            db_path=os.environ["YOKE_DB"],
        )
        assert count == 0  # Already seeded

    def test_get_requirement_after_seed(self, deploy_db):
        """get-requirement returns the ID of a seeded requirement."""
        deploy_db.execute(
            "INSERT INTO qa_requirements (deployment_run_id, qa_kind, qa_phase) "
            "VALUES ('run-1', 'smoke', 'post_deploy')",
        )
        deploy_db.commit()

        req_id = deploy_qa_recorder.cmd_get_requirement(
            "run-1", "smoke",
            db_path=os.environ["YOKE_DB"],
        )
        assert req_id is not None
        assert isinstance(req_id, int)
