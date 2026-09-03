"""Deployment-backed dependency satisfaction across gate consumers."""

from __future__ import annotations

import json
from typing import Any, Iterator

import pytest

from runtime.api.fixtures.schema_ddl import apply_fixture_ddl
from runtime.api.test_dependency_schema import create_dependency_test_db
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
    item_ids: tuple[int, ...],
) -> None:
    carried_work = json.dumps(
        {
            "schema": 1,
            "items": [{"item_id": item_id} for item_id in item_ids],
        }
    )
    conn.execute(
        "INSERT INTO deployment_runs "
        "(id,project_id,target_environment_id,status,carried_work) "
        "VALUES (%s,%s,%s,%s,%s)",
        (run_id, project_id, environment_id, status, carried_work),
    )


@pytest.mark.parametrize(
    "satisfaction,status,merged,expected",
    [
        ("status:done", "done", None, True),
        ("status:done", "implemented", None, False),
        ("status:implemented", "release", None, True),
        ("fact:merged", "implementing", True, True),
        ("fact:merged", "implementing", False, False),
    ],
)
def test_existing_satisfaction_values_are_unchanged(
    satisfaction: str,
    status: str,
    merged: bool | None,
    expected: bool,
) -> None:
    result = evaluate_satisfaction(
        satisfaction,
        status,
        blocking_merged=merged,
        workflow=WORKFLOW,
    )
    assert result.satisfied is expected


def test_deployed_value_joins_the_satisfaction_grammar() -> None:
    value = Satisfaction.from_db("fact:deployed:prod")
    assert value.value == "fact:deployed:prod"
    with pytest.raises(ValueError, match="accepted grammar"):
        Satisfaction.from_db("fact:released")


def test_deployed_evaluation_names_each_unsatisfied_state() -> None:
    registered = DeployedEnvironmentFact("prod", True, False)
    not_merged = evaluate_satisfaction(
        "fact:deployed:prod",
        "implementing",
        blocking_merged=False,
        blocking_deployed=registered,
        workflow=WORKFLOW,
    )
    assert not_merged.satisfied is False
    assert "not merged" in not_merged.reason

    merged = evaluate_satisfaction(
        "fact:deployed:prod",
        "implemented",
        blocking_merged=True,
        blocking_deployed=registered,
        workflow=WORKFLOW,
    )
    assert merged.satisfied is False
    assert "merged, not yet deployed to prod" in merged.reason

    removed = evaluate_satisfaction(
        "fact:deployed:prod",
        "done",
        blocking_deployed=DeployedEnvironmentFact("prod", False, False),
        workflow=WORKFLOW,
    )
    assert removed.satisfied is False
    assert removed.reason.startswith("environment_unregistered:")


def test_carried_work_is_the_authoritative_deployed_fact() -> None:
    result = evaluate_satisfaction(
        "fact:deployed:prod",
        "implementing",
        blocking_merged=False,
        blocking_deployed=DeployedEnvironmentFact("prod", True, True),
        workflow=WORKFLOW,
    )
    assert result.satisfied is True
    assert result.reason == "Blocking item is deployed to prod."


def test_any_succeeded_run_for_the_environment_satisfies_cumulatively(
    dependency_conn: Any,
) -> None:
    _insert_item(dependency_conn, 2, merged=True)
    _insert_run(
        dependency_conn,
        "earlier",
        project_id=1,
        environment_id=101,
        status="succeeded",
        item_ids=(2,),
    )
    _insert_run(
        dependency_conn,
        "later",
        project_id=1,
        environment_id=101,
        status="succeeded",
        item_ids=(),
    )
    result = evaluate_persisted_satisfaction(
        dependency_conn,
        blocking_item_id=2,
        satisfaction="fact:deployed:prod",
        blocking_status="implemented",
        blocking_merged=True,
        workflow=WORKFLOW,
    )
    assert result.satisfied is True


def test_other_environment_project_and_failed_runs_do_not_satisfy(
    dependency_conn: Any,
) -> None:
    _insert_item(dependency_conn, 2, merged=True)
    dependency_conn.execute(
        "INSERT INTO environments (id,site,project_id,name) "
        "VALUES (102,11,1,'stage')"
    )
    dependency_conn.execute(
        "INSERT INTO sites (id,project_id,name) VALUES (21,2,'external')"
    )
    dependency_conn.execute(
        "INSERT INTO environments (id,site,project_id,name) "
        "VALUES (201,21,2,'prod')"
    )
    _insert_run(
        dependency_conn,
        "stage-run",
        project_id=1,
        environment_id=102,
        status="succeeded",
        item_ids=(2,),
    )
    _insert_run(
        dependency_conn,
        "other-project",
        project_id=2,
        environment_id=201,
        status="succeeded",
        item_ids=(2,),
    )
    _insert_run(
        dependency_conn,
        "failed-prod",
        project_id=1,
        environment_id=101,
        status="failed",
        item_ids=(2,),
    )
    result = evaluate_persisted_satisfaction(
        dependency_conn,
        blocking_item_id=2,
        satisfaction="fact:deployed:prod",
        blocking_status="implemented",
        blocking_merged=True,
        workflow=WORKFLOW,
    )
    assert result.satisfied is False
    assert "merged, not yet deployed to prod" in result.reason


def test_removed_environment_fails_safe_without_raising(dependency_conn: Any) -> None:
    _insert_item(dependency_conn, 2, status="done", merged=True)
    dependency_conn.execute("DELETE FROM environments WHERE id=101")
    result = evaluate_persisted_satisfaction(
        dependency_conn,
        blocking_item_id=2,
        satisfaction="fact:deployed:prod",
        blocking_status="done",
        blocking_merged=True,
        workflow=WORKFLOW,
    )
    assert result.satisfied is False
    assert result.reason.startswith("environment_unregistered:")


def test_unknown_value_fails_safe_with_named_reason() -> None:
    result = evaluate_satisfaction("fact:released", "done", workflow=WORKFLOW)
    assert result.satisfied is False
    assert result.reason.startswith("unknown_satisfaction:")
    assert "fact:deployed:<environment-name>" in result.reason
