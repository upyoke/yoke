"""Shared native database and request fixtures for focused command tests."""

from __future__ import annotations

from yoke_contracts.timestamps import parse_instant
import json
import pytest
from runtime.api.fixtures.file_test_db import apply_inline_ddl, init_test_db


_ITEMS_DDL = """
CREATE TABLE projects (
    id INTEGER PRIMARY KEY, slug TEXT NOT NULL UNIQUE, name TEXT NOT NULL,
    public_item_prefix TEXT NOT NULL DEFAULT 'YOK'
);
CREATE TABLE items (
    id INTEGER PRIMARY KEY, title TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'idea', priority TEXT NOT NULL DEFAULT 'medium',
    frozen INTEGER DEFAULT 0, blocked INTEGER DEFAULT 0, blocked_reason TEXT,
    github_issue TEXT, deployed_to TEXT, merged_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL, updated_at TIMESTAMPTZ NOT NULL, source TEXT NOT NULL DEFAULT '2',
    project_id INTEGER NOT NULL REFERENCES projects(id),
    project_sequence INTEGER NOT NULL,
    deployment_flow TEXT, deploy_stage TEXT,
    UNIQUE(project_id, project_sequence)
);
CREATE TABLE deployment_flows (
    id TEXT PRIMARY KEY, project_id INTEGER NOT NULL REFERENCES projects(id), name TEXT NOT NULL, description TEXT,
    stages TEXT NOT NULL, on_failure TEXT DEFAULT 'halt', created_at TIMESTAMPTZ NOT NULL,
    target_tier TEXT DEFAULT NULL, target_environment_id TEXT DEFAULT NULL,
    done_description TEXT DEFAULT NULL,
    UNIQUE(project_id, name)
);
"""


_SEED_ITEMS = [
    (1, "Active item", "implementing", "high", 1, 1, 0),
    (2, "Done item", "done", "medium", 1, 2, 0),
    (3, "Cancelled item", "cancelled", "low", 1, 3, 0),
    (4, "Frozen item", "idea", "medium", 1, 4, 1),
    (5, "ExternalWebapp active", "implementing", "medium", 2, 1, 0),
]


def _seed_items_and_flow() -> None:
    """``apply_schema`` strategy: minimal schema + fixture rows."""
    from yoke_core.domain import db_backend

    apply_inline_ddl(_ITEMS_DDL)
    conn = db_backend.connect()
    try:
        from yoke_core.domain import workflow_registry, workflow_schema

        workflow_schema.ensure_workflow_schema(conn)
        workflow_registry.converge_builtin_workflows(conn)
        workflow_pin = workflow_registry.resolve_current_workflow_pin(conn, "issue")
        workflow_id, workflow_version_id = workflow_pin
        stages_json = json.dumps(
            [
                {"name": "merged", "step_runner": "auto"},
                {"name": "approve-deploy", "step_runner": "human-approval"},
                {"name": "prod-deploy", "step_runner": "github-actions-workflow"},
                {"name": "complete", "step_runner": "auto"},
            ]
        )
        conn.execute(
            "INSERT INTO projects (id, slug, name, public_item_prefix) "
            "VALUES (1, 'yoke', 'Yoke', 'YOK'), (2, 'externalwebapp', 'ExternalWebapp', 'EXT')"
        )
        conn.execute(
            """INSERT INTO deployment_flows (id, project_id, name, stages, created_at)
               VALUES ('test-flow', 1, 'TestFlow', %s, %s)""",
            (stages_json, parse_instant("2026-04-20T00:00:00Z")),
        )
        for (
            item_id,
            title,
            status,
            priority,
            project_id,
            project_sequence,
            frozen,
        ) in _SEED_ITEMS:
            conn.execute(
                """INSERT INTO items (
                                      id, title, workflow_id, workflow_version_id,
                                      status, priority, project_id, project_sequence,
                                      created_at, updated_at, source, frozen)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s,
                           '2026-01-01T00:00:00.123456Z', '2026-01-01T00:00:00.123456Z', 'user', %s)""",
                (
                    item_id,
                    title,
                    workflow_id,
                    workflow_version_id,
                    status,
                    priority,
                    project_id,
                    project_sequence,
                    frozen,
                ),
            )
        conn.commit()
    finally:
        conn.close()


@pytest.fixture()
def test_db(tmp_path):
    """Backend-aware fixture seeding the deployment flow + items."""
    with init_test_db(tmp_path, apply_schema=_seed_items_and_flow) as db_path:
        yield {"db_path": db_path}
