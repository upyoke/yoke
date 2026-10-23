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
                "--test-machine",
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


def test_failure_notice_help_reaches_installed_recovery_without_execution(capsys) -> None:
    from pathlib import Path

    from yoke_cli.commands import qa_case
    from yoke_core.domain.deployment_qa_failure_handoff import failure_handoff_message

    notice = failure_handoff_message(
        run_id="run-example", stage="member-qa", item_ref="APP-1", requirement_ids=(1,)
    )
    assert "yoke qa plan run --help" in notice
    with mock.patch.object(qa_case, "_run_execution_module") as execute:
        assert qa_case.qa_plan_run(["--help"]) == 0
    execute.assert_not_called()
    help_text = capsys.readouterr().out
    installed_recipe = ".yoke/docs/verification/failed-item-qa.md"
    assert installed_recipe in help_text
    root = Path(__file__).resolve().parents[3]
    assert (root / "docs/public/verification/failed-item-qa.md").is_file()
    bundle = root / "packages/yoke-core/src/yoke_core/install_bundle_tree"
    assert (bundle / "docs/public/verification/failed-item-qa.md").is_file()
