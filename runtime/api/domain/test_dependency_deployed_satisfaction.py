"""Deployment-backed dependency satisfaction across gate consumers."""

from __future__ import annotations

from runtime.api.domain.dependency_deployed_satisfaction_test_support import (
    DEPLOYMENT_SCHEMA as DEPLOYMENT_SCHEMA,
    NOW as NOW,
    WORKFLOW as WORKFLOW,
    _insert_edge as _insert_edge,
    _insert_item as _insert_item,
    _insert_run as _insert_run,
    dependency_conn as dependency_conn,
)


from typing import Any

import pytest

from yoke_core.domain.dependencies import Satisfaction
from yoke_core.domain.dependency_satisfaction import (
    DeployedEnvironmentFact,
    evaluate_persisted_satisfaction,
    evaluate_satisfaction,
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
def test_satisfaction_values_with_recorded_merge_evidence(
    satisfaction: str,
    status: str,
    merged: bool | None,
    expected: bool,
) -> None:
    result = evaluate_satisfaction(
        satisfaction,
        status,
        blocking_merged=merged,
        blocking_merged_at=NOW if merged else None,
        dependency_created_at="2026-01-01T00:00:00Z",
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


def test_completion_fact_cannot_satisfy_an_incomplete_item() -> None:
    result = evaluate_satisfaction(
        "fact:deployed:prod",
        "implementing",
        blocking_merged=False,
        blocking_deployed=DeployedEnvironmentFact("prod", True, True),
        workflow=WORKFLOW,
    )
    assert result.satisfied is False


def test_any_succeeded_run_for_the_environment_satisfies_cumulatively(
    dependency_conn: Any,
) -> None:
    _insert_item(dependency_conn, 2, status="done", merged=True)
    _insert_run(
        dependency_conn,
        "earlier",
        project_id=1,
        environment_id=101,
        status="succeeded",
        member_ids=(2,),
    )
    _insert_run(
        dependency_conn,
        "later",
        project_id=1,
        environment_id=101,
        status="succeeded",
    )
    result = evaluate_persisted_satisfaction(
        dependency_conn,
        blocking_item_id=2,
        satisfaction="fact:deployed:prod",
        blocking_status="done",
        blocking_merged=True,
        workflow=WORKFLOW,
    )
    assert result.satisfied is True
    assert (
        evaluate_persisted_satisfaction(
            dependency_conn,
            blocking_item_id=2,
            satisfaction="status:done",
            blocking_status="done",
            workflow=WORKFLOW,
        ).satisfied
        is True
    )


def test_other_environment_failed_and_cancelled_runs_do_not_satisfy(
    dependency_conn: Any,
) -> None:
    _insert_item(dependency_conn, 2, merged=True)
    dependency_conn.execute(
        "INSERT INTO environments (id,site,project_id,name) VALUES (102,11,1,'stage')"
    )
    dependency_conn.execute(
        "INSERT INTO sites (id,project_id,name) VALUES (21,2,'external')"
    )
    dependency_conn.execute(
        "INSERT INTO environments (id,site,project_id,name) VALUES (201,21,2,'prod')"
    )
    _insert_run(
        dependency_conn,
        "stage-run",
        project_id=1,
        environment_id=102,
        status="succeeded",
        member_ids=(2,),
    )
    _insert_run(
        dependency_conn,
        "other-project",
        project_id=2,
        environment_id=201,
        status="failed",
        member_ids=(2,),
    )
    _insert_run(
        dependency_conn,
        "failed-prod",
        project_id=1,
        environment_id=101,
        status="failed",
        member_ids=(2,),
    )
    _insert_run(
        dependency_conn,
        "cancelled-prod",
        project_id=1,
        environment_id=101,
        status="cancelled",
        member_ids=(2,),
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
