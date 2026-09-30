"""CLI coverage for deployment-run QA plan execution."""

from __future__ import annotations

import json
from unittest import mock

import pytest

from yoke_core.domain import qa_plan_execution_cli


def test_plan_help_carries_the_failed_member_notice_recovery(capsys) -> None:
    with pytest.raises(SystemExit) as exit_info:
        qa_plan_execution_cli.run(["--help"])
    assert exit_info.value.code == 0
    help_text = capsys.readouterr().out
    assert "Failed member QA recovery" in help_text
    assert "qa run list --requirement-id FAILED_REQUIREMENT_ID" in help_text
    assert (
        "yoke watch qa-plan -- --deployment-run-id RUN --stage STAGE --member ITEM"
        in help_text
    )
    assert "--replaces CASE_KEY=FAILED_REQUIREMENT_ID" in help_text
    assert "--from release --to implementing" in help_text
    assert "new run must deploy the corrected commit" in help_text


def test_plan_engine_cli_accepts_deployment_run_subject(capsys) -> None:
    deployment_run_id = "run-20260728-901"
    with mock.patch.object(
        qa_plan_execution_cli,
        "execute_plan",
        return_value={
            "item_id": None,
            "deployment_run_id": deployment_run_id,
            "transition_id": None,
            "state": "passed",
            "requirement_count": 1,
            "executed_count": 1,
            "results": [],
        },
    ) as execute:
        code = qa_plan_execution_cli.run(
            [
                "--deployment-run-id",
                deployment_run_id,
                "--plan",
                "installer-campaign",
                "--project",
                "yoke",
                "--machine",
                "mac-studio-lab",
                "--session-id",
                "deployment-plan-session",
            ]
        )

    assert code == 0
    assert json.loads(capsys.readouterr().out)["deployment_run_id"] == deployment_run_id
    assert execute.call_args.kwargs["public_ref"] is None
    assert execute.call_args.kwargs["deployment_run_id"] == deployment_run_id
    assert execute.call_args.kwargs["plan"] == "installer-campaign"
    assert execute.call_args.kwargs["machine"] == "mac-studio-lab"
    assert execute.call_args.kwargs["checkout_path"] is None


def test_plan_engine_cli_forwards_checkout_path(capsys) -> None:
    deployment_run_id = "run-20260728-901"
    checkout = "/tmp/candidate-checkout"
    with mock.patch.object(
        qa_plan_execution_cli,
        "execute_plan",
        return_value={
            "item_id": None,
            "deployment_run_id": deployment_run_id,
            "transition_id": None,
            "state": "passed",
            "requirement_count": 1,
            "executed_count": 1,
            "results": [],
        },
    ) as execute:
        code = qa_plan_execution_cli.run(
            [
                "--deployment-run-id",
                deployment_run_id,
                "--plan",
                "installer-campaign",
                "--project",
                "yoke",
                "--checkout-path",
                checkout,
                "--session-id",
                "deployment-plan-session",
            ]
        )

    assert code == 0
    assert json.loads(capsys.readouterr().out)["deployment_run_id"] == deployment_run_id
    assert execute.call_args.kwargs["checkout_path"] == checkout
    assert execute.call_args.kwargs["deployment_run_id"] == deployment_run_id
