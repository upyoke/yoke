"""A deployment QA stage asks its frozen target what it serves before starting.

A different served build is reported as an observation and QA proceeds; a
target that cannot be asked is reported as unverified.
"""

from __future__ import annotations

from unittest import mock

import pytest

from yoke_contracts.api.function_call import ActorContext
from yoke_core.domain import qa_plan_execution
from yoke_core.domain import served_revision_probe as probe
from yoke_core.domain.deployment_qa_start_identity import (
    START_IDENTITY_FIELD,
    report_start_identity,
    start_identity_expectation,
)

DELIVERED = "c" * 40
SERVED = "d" * 40


def _expectation(identity_path: str = "/candidate-revision") -> dict:
    return {
        START_IDENTITY_FIELD: {
            "target": {
                "environment": "stage",
                "origin": "https://app.stage.example.test",
                "identity_path": identity_path,
            },
            "expected_sha": DELIVERED,
            "project": "webapp",
        }
    }


def _serving(sha: str):
    return lambda _url: probe.ServedRevisionRead(status=200, body=sha, error="")


def test_a_target_serving_the_delivered_build_reports_nothing(
    capsys: pytest.CaptureFixture[str],
) -> None:
    report_start_identity(
        _expectation(), run_id="run-1", stage="item-qa", fetch=_serving(DELIVERED)
    )
    err = capsys.readouterr().err
    assert "observed at QA start" not in err and "unverified" not in err


def test_an_unaskable_target_is_unverified(
    capsys: pytest.CaptureFixture[str],
) -> None:
    report_start_identity(_expectation(identity_path=""), run_id="run-1", stage="item-qa")
    assert "identity at QA start unverified" in capsys.readouterr().err


def test_a_different_served_build_proceeds_and_is_reported(
    capsys: pytest.CaptureFixture[str],
) -> None:
    roster = {
        "execution_id": "exec-1",
        "state": "active",
        "cursor_ordinal": 0,
        "remaining_requirement_count": 0,
        "results": [],
        "deployment_run_id": "run-1",
        "deployment_stage": "item-qa",
        "execution_target": {"environment": {"name": "stage"}, "endpoints": {}},
        "requirements": [
            {
                "requirement_id": 10,
                "plan_id": 1,
                "case_key": "reset",
                "case_position": 1,
                "baseline_position": 1,
                "host_baseline": "fresh-host",
                "starting_state": "baseline",
                "runner_id": "host_control",
                "required_capability_kinds": ["test-machine:lab"],
            }
        ],
        **_expectation(),
    }
    calls: list[str] = []

    def dispatch(**kwargs):
        calls.append(kwargs["function_id"])
        return roster if kwargs["function_id"] == "qa.plan_execution.begin" else {}

    with (
        mock.patch.object(
            qa_plan_execution, "_call_plan_function", side_effect=dispatch
        ),
        mock.patch.object(probe, "fetch_served_revision", _serving(SERVED)),
        mock.patch(
            "yoke_core.domain.qa_plan_execution_run.execute_begun_plan"
        ) as execute,
    ):
        qa_plan_execution.execute_plan(
            deployment_run_id="run-1",
            deployment_stage="item-qa",
            project="webapp",
            actor=ActorContext(actor_id="2", session_id="walker"),
        )
    err = capsys.readouterr().err
    assert "observed at QA start" in err and SERVED in err and DELIVERED in err
    assert execute.call_count == 1
    assert "qa.plan_execution.abort" not in calls


def test_a_shared_item_qa_resume_resolves_its_target() -> None:
    """A shared execution has no member item; its frozen target names the plan."""
    execution = {
        "deployment_run_id": "run-1",
        "deployment_stage": "item-qa",
        "deployment_member_item_id": None,
        "execution_target": {"deployment": {"shared_plan": {"plan_id": 7}}},
    }
    conn = mock.Mock()
    conn.execute.return_value.fetchone.return_value = {
        "url": "https://app.stage.example.test"
    }
    domain = "yoke_core.domain."
    with (
        mock.patch(
            domain + "deployment_qa_shared_plans.resolve_shared_subject",
            return_value={"id": "run-1", "stage": {"name": "item-qa"}},
        ) as shared,
        mock.patch(
            domain + "deployment_qa_execution_target.deployment_qa_execution_target",
            return_value={
                "environment": {"kind": "persistent_environment", "name": "stage"}
            },
        ),
        mock.patch(
            domain + "deployment_qa_target_project.target_project",
            return_value={"id": 3, "slug": "webapp"},
        ),
        mock.patch(
            domain + "deployment_run_project_sources.run_delivered_sha",
            return_value=DELIVERED,
        ),
        mock.patch(
            domain + "deployment_target_identity_config.persistent_identity_path",
            return_value=mock.Mock(path="/candidate-revision", error=""),
        ),
        mock.patch(domain + "db_backend.connection_is_postgres", return_value=False),
    ):
        expectation = start_identity_expectation(conn, execution)
    assert shared.call_args.kwargs["plan_id"] == 7
    assert expectation is not None
    assert not expectation["target"].get("unresolved")
    assert expectation["target"]["environment"] == "stage"
    assert expectation["expected_sha"] == DELIVERED
