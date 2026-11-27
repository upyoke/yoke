"""Compact operator-abort CLI coverage."""

from __future__ import annotations

import json
from unittest import mock

from yoke_core.domain import qa_plan_execution_abort_cli
from yoke_core.domain.handlers.qa_plan_execution_models import (
    PlanExecutionStateResponse,
)


def _run(response: dict):
    with (
        mock.patch.object(
            qa_plan_execution_abort_cli, "_call_plan_function", return_value=response
        ),
        mock.patch(
            "yoke_core.api.service_client_structured_api_adapter.build_actor",
            return_value="actor",
        ),
    ):
        return qa_plan_execution_abort_cli.run(
            ["--execution-id", "execution-1", "--reason", "operator-interrupt"]
        )


HOLDOVER = {
    "claim_id": 41,
    "test_machine": "lab-wsl",
    "expires_at": "2026-11-27T07:20:00Z",
}


def test_abort_receipt_shows_kept_holdovers(capsys) -> None:
    """Feedback 98869: the settled abort names the hosts its session still holds."""
    declared = PlanExecutionStateResponse.model_validate(
        {
            "execution_id": "execution-1",
            "state": "aborted",
            "roster_digest": "digest",
            "cursor_ordinal": 0,
            "requirements": [],
            "results": [],
            "test_machine_holdovers": [HOLDOVER],
        }
    ).model_dump(mode="json")
    assert declared["test_machine_holdovers"] == [HOLDOVER]
    assert _run(declared) == 0
    receipt = json.loads(capsys.readouterr().out)
    assert receipt["test_machine_holdovers"] == [HOLDOVER]


def test_abort_receipt_omits_absent_holdovers(capsys) -> None:
    # Older servers send no list; an empty one keeps nothing.
    for holdovers in ({}, {"test_machine_holdovers": []}):
        response = {"execution_id": "execution-1", "state": "aborted", **holdovers}
        assert _run(response) == 0
        assert "test_machine_holdovers" not in json.loads(capsys.readouterr().out)


def test_abort_prints_compact_receipt(capsys) -> None:
    response = {
        "execution_id": "execution-1",
        "item_id": None,
        "deployment_run_id": "run-1",
        "transition_id": None,
        "state": "aborted",
        "cursor_ordinal": 3,
        "test_machine_lease_id": None,
        "requirements": [{"large": "roster"}],
        "results": [{"large": "results"}],
    }
    with (
        mock.patch.object(
            qa_plan_execution_abort_cli,
            "_call_plan_function",
            return_value=response,
        ) as call,
        mock.patch(
            "yoke_core.api.service_client_structured_api_adapter.build_actor",
            return_value="actor",
        ),
    ):
        exit_code = qa_plan_execution_abort_cli.run(
            [
                "--execution-id",
                "execution-1",
                "--reason",
                "operator-interrupt",
                "--project",
                "yoke",
            ]
        )

    assert exit_code == 0
    assert json.loads(capsys.readouterr().out) == {
        "cursor_ordinal": 3,
        "deployment_run_id": "run-1",
        "execution_id": "execution-1",
        "item_id": None,
        "test_machine_lease_id": None,
        "state": "aborted",
        "transition_id": None,
    }
    assert call.call_args.kwargs["function_id"] == "qa.plan_execution.abort"
    assert call.call_args.kwargs["payload"] == {
        "execution_id": "execution-1",
        "reason": "operator-interrupt",
    }
    assert call.call_args.kwargs["target"].deployment_run_id is None
    assert call.call_args.kwargs["target"].project_id == "yoke"
