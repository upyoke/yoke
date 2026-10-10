"""A deployment QA stage asks its frozen target what it serves before starting.

Drift refuses before any host reset; a target that cannot be asked is
reported as unverified and the stage starts as it did before.
"""

from __future__ import annotations

from unittest import mock

import pytest

from yoke_contracts.api.function_call import ActorContext
from yoke_core.domain import qa_plan_execution
from yoke_core.domain import served_revision_probe as probe
from yoke_core.domain.deployment_qa_start_identity import (
    DRIFT_CODE,
    START_IDENTITY_FIELD,
    require_start_identity,
)
from yoke_core.domain.qa_plan_execution_result_state import QaPlanExecutionError

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


def test_a_target_serving_the_delivered_build_starts() -> None:
    assert (
        require_start_identity(
            _expectation(), run_id="run-1", stage="item-qa", fetch=_serving(DELIVERED)
        )
        is None
    )


def test_a_drifted_target_refuses_naming_both_builds() -> None:
    refusal = require_start_identity(
        _expectation(), run_id="run-1", stage="item-qa", fetch=_serving(SERVED)
    )
    assert refusal is not None and refusal.startswith(DRIFT_CODE)
    assert DELIVERED in refusal and SERVED in refusal
    assert "No host was reset" in refusal


def test_an_unaskable_target_is_unverified_not_refused(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert (
        require_start_identity(
            _expectation(identity_path=""), run_id="run-1", stage="item-qa"
        )
        is None
    )
    assert "identity at QA start unverified" in capsys.readouterr().err


def test_a_server_without_the_field_starts_as_before() -> None:
    assert require_start_identity({}, run_id="run-1", stage="item-qa") is None


def test_drift_refuses_before_the_roster_reaches_a_host_reset() -> None:
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
        with pytest.raises(QaPlanExecutionError) as refused:
            qa_plan_execution.execute_plan(
                deployment_run_id="run-1",
                deployment_stage="item-qa",
                project="webapp",
                actor=ActorContext(actor_id="2", session_id="walker"),
            )
    assert DRIFT_CODE in str(refused.value)
    assert execute.call_count == 0
    assert "qa.plan_execution.abort" in calls
