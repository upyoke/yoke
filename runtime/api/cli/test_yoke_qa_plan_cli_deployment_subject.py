"""CLI coverage for deployment-run QA plan execution."""

from __future__ import annotations

import json
from unittest import mock

from yoke_core.domain import qa_plan_execution_cli


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
