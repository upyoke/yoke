"""Strict project-identity schema and seed data for service-client parity tests."""

from __future__ import annotations

import json
from typing import Any

from runtime.api.test_dependency_schema import ITEMS_SCHEMA, PROJECTS_SCHEMA
from yoke_core.domain.strategy_docs import STRATEGY_DOCS_CREATE_TABLE_SQL


SERVICE_CLIENT_PARITY_SCHEMA = (
    PROJECTS_SCHEMA
    + ITEMS_SCHEMA
    + STRATEGY_DOCS_CREATE_TABLE_SQL
    + ";\n"
    + """
    CREATE TABLE deployment_flows (
        id TEXT PRIMARY KEY,
        project_id INTEGER NOT NULL REFERENCES projects(id),
        name TEXT NOT NULL,
        description TEXT,
        stages TEXT NOT NULL,
        on_failure TEXT DEFAULT 'halt',
        created_at TEXT NOT NULL,
        target_env TEXT DEFAULT NULL,
        done_description TEXT DEFAULT NULL,
        UNIQUE(project_id, name)
    );

    CREATE TABLE deployment_runs (
        id TEXT PRIMARY KEY,
        project_id INTEGER NOT NULL REFERENCES projects(id),
        flow TEXT NOT NULL,
        target_env TEXT,
        release_lineage TEXT,
        status TEXT NOT NULL DEFAULT 'created'
          CHECK(status IN ('created','executing','succeeded','failed','cancelled')),
        current_stage TEXT,
        created_at TEXT NOT NULL,
        started_at TEXT,
        completed_at TEXT,
        created_by TEXT DEFAULT 'operator'
    );

    CREATE TABLE deployment_run_items (
        run_id TEXT NOT NULL,
        item_id INTEGER NOT NULL,
        added_at TEXT NOT NULL,
        PRIMARY KEY (run_id, item_id)
    );

    CREATE TABLE project_capabilities (
        id INTEGER PRIMARY KEY,
        project_id INTEGER NOT NULL REFERENCES projects(id),
        type TEXT NOT NULL,
        settings TEXT DEFAULT '{}',
        verified_at TEXT,
        created_at TEXT NOT NULL,
        UNIQUE(project_id, type)
    );
"""
)


def _execute(conn: Any, statement: str, params: tuple[Any, ...] = ()) -> None:
    conn.execute(statement, params)


def _project_id(slug: str) -> int:
    return 2 if slug == "buzz" else 1


def seed_service_client_parity_data(conn: Any) -> None:
    """Seed the service-client parity dataset on the strict project schema."""
    ts = "2026-03-01T00:00:00Z"
    items = (
        (1, "Implementing item", "task", "implementing", "high", "yoke", 1, None, None, 0),
        (2, "Done item", "epic", "done", "medium", "yoke", 2, None, None, 0),
        (3, "Buzz idea", "issue", "idea", "low", "buzz", 1, None, None, 0),
        (
            4, "Awaiting approval", "issue", "release", "high", "yoke", 3,
            "approve-deploy", "parity-flow", 0,
        ),
        (5, "Cancelled item", "issue", "cancelled", "low", "yoke", 4, None, None, 0),
        (6, "Frozen item", "issue", "planned", "medium", "yoke", 5, None, None, 1),
        (
            7, "Reviewing item", "issue", "reviewing-implementation", "high",
            "yoke", 6, None, None, 0,
        ),
        (
            8, "Implemented with run", "issue", "implemented", "medium", "yoke", 7,
            "prod-deploy", "parity-flow", 0,
        ),
        (9, "Blocked item", "issue", "blocked", "high", "yoke", 8, None, None, 0),
    )
    for item in items:
        _execute(
            conn,
            """INSERT INTO items
               (id, title, type, status, priority, project_id, project_sequence,
                created_at, updated_at, source, frozen, deploy_stage, deployment_flow)
               VALUES (%s, %s, %s, %s, %s, %s, %s,
                       %s, %s, 'user', %s, %s, %s)""",
            (
                item[0], item[1], item[2], item[3], item[4],
                _project_id(item[5]), item[6], ts, ts, item[9], item[7], item[8],
            ),
        )

    flow_stages = json.dumps([
        {"name": "merged", "executor": "auto"},
        {"name": "approve-deploy", "executor": "human-approval"},
        {"name": "prod-deploy", "executor": "github-actions-workflow"},
        {"name": "complete", "executor": "auto"},
    ])
    _execute(
        conn,
        """INSERT INTO deployment_flows (id, project_id, name, stages, created_at)
           VALUES ('parity-flow', 1, 'ParityFlow', %s, %s)""",
        (flow_stages, ts),
    )
    _execute(
        conn,
        """INSERT INTO deployment_runs
           (id, project_id, flow, status, current_stage, created_at)
           VALUES ('run-parity-001', 1, 'parity-flow', 'executing',
                   'approve-deploy', %s)""",
        (ts,),
    )
    _execute(
        conn,
        """INSERT INTO deployment_run_items (run_id, item_id, added_at)
           VALUES ('run-parity-001', 4, %s)""",
        (ts,),
    )
    _execute(
        conn,
        """INSERT INTO deployment_runs
           (id, project_id, flow, status, current_stage, created_at)
           VALUES ('run-parity-002', 1, 'parity-flow', 'executing',
                   'prod-deploy', %s)""",
        (ts,),
    )
    _execute(
        conn,
        """INSERT INTO deployment_run_items (run_id, item_id, added_at)
           VALUES ('run-parity-002', 8, %s)""",
        (ts,),
    )
    conn.commit()


__all__ = [
    "SERVICE_CLIENT_PARITY_SCHEMA",
    "seed_service_client_parity_data",
]
