# ruff: noqa: F811
"""Deployment composition consumes the canonical dependency evaluator."""

from __future__ import annotations

import json
from typing import Any

from runtime.api.test_deployment_runs_full_helpers import (  # noqa: F401
    _conn,
    db_path,
)
from yoke_core.domain import deployment_runs as dr
from yoke_core.domain.dependency_satisfaction import evaluate_persisted_satisfaction
from yoke_core.domain.workflow_registry import resolve_current_workflow_pin
from runtime.api.domain.test_dependency_deployed_satisfaction import (
    WORKFLOW,
    _insert_item as insert_dependency_item,
    _insert_run,
    dependency_conn,  # noqa: F401
)


NOW = "2026-09-03T12:00:00Z"


def _insert_item(conn: Any, item_id: int) -> None:
    workflow_id, workflow_version_id = resolve_current_workflow_pin(conn, "issue")
    conn.execute(
        "INSERT INTO items "
        "(id,title,workflow_id,workflow_version_id,status,project_id,"
        "project_sequence,merged_at,created_at,updated_at) "
        "VALUES (%s,'item',%s,%s,'implemented',1,%s,%s,%s,%s)",
        (
            item_id,
            workflow_id,
            workflow_version_id,
            item_id,
            NOW,
            NOW,
            NOW,
        ),
    )


def _seed_validation(db_path: str, *, with_delivery_fact: bool) -> str:
    current_run = dr.cmd_create_run("yoke", "yoke-internal", db_path=db_path)
    conn = _conn(db_path)
    _insert_item(conn, 100)
    _insert_item(conn, 200)
    conn.execute(
        "INSERT INTO item_dependencies "
        "(dependent_item_id,blocking_item_id,gate_point,satisfaction,source,created_at) "
        "VALUES (100,200,'activation','fact:deployed:prod','test',%s)",
        (NOW,),
    )
    conn.commit()
    conn.close()
    dr.cmd_add_item(current_run, 100, db_path=db_path)
    if with_delivery_fact:
        prior_run = dr.cmd_create_run(
            "yoke",
            "yoke-internal",
            environment="prod",
            db_path=db_path,
        )
        conn = _conn(db_path)
        conn.execute(
            "UPDATE deployment_runs SET status='succeeded',carried_work=%s WHERE id=%s",
            (json.dumps({"schema": 1, "items": [{"item_id": 200}]}), prior_run),
        )
        conn.execute(
            "INSERT INTO deployment_run_items (run_id,item_id,added_at) "
            "VALUES (%s,200,%s)",
            (prior_run, NOW),
        )
        conn.commit()
        conn.close()
    return current_run


def test_composition_accepts_a_prior_succeeded_delivery(db_path: str) -> None:
    run_id = _seed_validation(db_path, with_delivery_fact=True)
    assert dr.cmd_validate_composition(run_id, db_path=db_path) == (True, "OK")


def test_composition_reports_missing_environment_delivery(db_path: str) -> None:
    run_id = _seed_validation(db_path, with_delivery_fact=False)
    ok, message = dr.cmd_validate_composition(run_id, db_path=db_path)
    assert ok is False
    assert "merged, not yet deployed to prod" in message


def test_cross_project_progress_member_is_deployed_before_done(
    dependency_conn: Any,
) -> None:
    insert_dependency_item(dependency_conn, 2, status="implemented", merged=True)
    dependency_conn.execute(
        "INSERT INTO sites (id,project_id,name) VALUES (21,2,'external')"
    )
    dependency_conn.execute(
        "INSERT INTO environments (id,site,project_id,name) VALUES (201,21,2,'prod')"
    )
    _insert_run(
        dependency_conn,
        "progress-run",
        project_id=2,
        environment_id=201,
        status="succeeded",
        member_ids=(2,),
    )
    deployed = evaluate_persisted_satisfaction(
        dependency_conn,
        blocking_item_id=2,
        satisfaction="fact:deployed:prod",
        blocking_status="implemented",
        blocking_merged=True,
        workflow=WORKFLOW,
    )
    done = evaluate_persisted_satisfaction(
        dependency_conn,
        blocking_item_id=2,
        satisfaction="status:done",
        blocking_status="implemented",
        blocking_merged=True,
        workflow=WORKFLOW,
    )
    assert deployed.satisfied is True
    assert done.satisfied is False


def test_carried_code_without_membership_does_not_satisfy(
    dependency_conn: Any,
) -> None:
    insert_dependency_item(dependency_conn, 2, merged=True)
    _insert_run(
        dependency_conn,
        "contained-only",
        project_id=1,
        environment_id=101,
        status="succeeded",
        carried_ids=(2,),
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


def test_another_projects_release_satisfies_its_bound_member(
    dependency_conn: Any,
) -> None:
    """A project-2 blocker delivered inside a project-1 release is deployed."""
    insert_dependency_item(
        dependency_conn, 2, status="implemented", project_id=2, merged=True
    )
    # The carrier's prod (101) is seeded; the bound project registers its own.
    dependency_conn.execute(
        "INSERT INTO sites (id,project_id,name) VALUES (22,2,'bound')"
    )
    dependency_conn.execute(
        "INSERT INTO environments (id,site,project_id,name) VALUES (202,22,2,'prod')"
    )
    _insert_run(
        dependency_conn,
        "carrier-run",
        project_id=1,
        environment_id=101,
        status="succeeded",
        member_ids=(2,),
    )

    deployed = evaluate_persisted_satisfaction(
        dependency_conn,
        blocking_item_id=2,
        satisfaction="fact:deployed:prod",
        blocking_status="implemented",
        blocking_merged=True,
        workflow=WORKFLOW,
    )

    assert deployed.satisfied is True
