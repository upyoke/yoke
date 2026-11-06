# ruff: noqa: F401, E402
"""Shared setup for tests in this directory."""

from __future__ import annotations

import json

from typing import Any, Iterator

import pytest

from runtime.api.fixtures.schema_ddl import apply_fixture_ddl

from runtime.api.dependency_schema_test_support import create_dependency_test_db

from yoke_core.domain.dependencies import Satisfaction

from yoke_core.domain.dependency_satisfaction import (
    DeployedEnvironmentFact,
    evaluate_persisted_satisfaction,
    evaluate_satisfaction,
)

from yoke_core.domain.workflow_registry import resolve_current_workflow_pin

from yoke_core.domain.workflow_runtime import builtin_workflow_runtime

WORKFLOW = builtin_workflow_runtime("issue")

NOW = "2026-09-03T12:00:00Z"

DEPLOYMENT_SCHEMA = """
CREATE TABLE sites (
  id INTEGER PRIMARY KEY,
  project_id INTEGER NOT NULL,
  name TEXT NOT NULL
);
CREATE TABLE environments (
  id INTEGER PRIMARY KEY,
  site INTEGER NOT NULL,
  project_id INTEGER NOT NULL,
  name TEXT NOT NULL,
  UNIQUE(project_id, name)
);
CREATE TABLE deployment_runs (
  id TEXT PRIMARY KEY,
  project_id INTEGER NOT NULL,
  target_environment_id INTEGER,
  status TEXT NOT NULL,
  carried_work TEXT
);
CREATE TABLE deployment_run_items (
  run_id TEXT NOT NULL,
  item_id INTEGER NOT NULL
);
CREATE TABLE path_claims (
  id INTEGER PRIMARY KEY,
  state TEXT NOT NULL,
  blocked_reason TEXT,
  integration_target TEXT,
  owner_item_id INTEGER
);
INSERT INTO sites (id, project_id, name) VALUES (11, 1, 'yoke');
INSERT INTO environments (id, site, project_id, name)
VALUES (101, 11, 1, 'prod');
"""


@pytest.fixture()
def dependency_conn() -> Iterator[Any]:
    conn = create_dependency_test_db()
    apply_fixture_ddl(conn, DEPLOYMENT_SCHEMA)
    try:
        yield conn
    finally:
        conn.close()


def _insert_item(
    conn: Any,
    item_id: int,
    *,
    status: str = "implementing",
    project_id: int = 1,
    merged: bool = False,
) -> None:
    workflow_id, workflow_version_id = resolve_current_workflow_pin(conn, "issue")
    conn.execute(
        "INSERT INTO items "
        "(id,title,workflow_id,workflow_version_id,status,project_id,"
        "project_sequence,merged_at,created_at,updated_at) "
        "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
        (
            item_id,
            f"Item {item_id}",
            workflow_id,
            workflow_version_id,
            status,
            project_id,
            item_id,
            NOW if merged else None,
            NOW,
            NOW,
        ),
    )


def _insert_edge(
    conn: Any,
    dependent: int,
    blocker: int,
    satisfaction: str = "fact:deployed:prod",
) -> None:
    conn.execute(
        "INSERT INTO item_dependencies "
        "(dependent_item_id,blocking_item_id,gate_point,satisfaction,source,created_at) "
        "VALUES (%s,%s,'activation',%s,'test',%s)",
        (dependent, blocker, satisfaction, NOW),
    )


def _insert_run(
    conn: Any,
    run_id: str,
    *,
    project_id: int,
    environment_id: int,
    status: str,
    member_ids: tuple[int, ...] = (),
    carried_ids: tuple[int, ...] = (),
) -> None:
    carried_work = json.dumps(
        {
            "schema": 1,
            "items": [{"item_id": item_id} for item_id in carried_ids],
        }
    )
    conn.execute(
        "INSERT INTO deployment_runs "
        "(id,project_id,target_environment_id,status,carried_work) "
        "VALUES (%s,%s,%s,%s,%s)",
        (run_id, project_id, environment_id, status, carried_work),
    )
    for item_id in member_ids:
        conn.execute(
            "INSERT INTO deployment_run_items (run_id,item_id) VALUES (%s,%s)",
            (run_id, item_id),
        )
    if status == "succeeded":
        from runtime.api.domain.dependency_delivery_test_support import (
            stamp_completed_members,
        )

        stamp_completed_members(conn, run_id)
