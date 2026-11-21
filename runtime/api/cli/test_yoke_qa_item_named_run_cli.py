"""`--item PREFIX-N --stage S --deployment-run-id RUN` on all three QA commands.

The holder names the run when several live runs could answer the item's
stage. The run travels as the ``deployment_run_id`` argument; the server
validates it, and the CLI refuses a receipt that answered another run.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from yoke_cli.commands.adapters.qa_execution_subjects import (
    qa_plan_materialize_for_item,
    qa_plan_rematerialize,
)
from yoke_contracts.api.function_call import FunctionCallResponse
from yoke_contracts.qa_item_run_selection_receipt import selected_run_mismatch
from yoke_core.domain import qa_plan_execution_cli
from yoke_core.domain.qa_plan_execution import require_selected_run
from yoke_core.domain.qa_plan_execution_result_state import QaPlanExecutionError
from yoke_core.domain.qa_plan_execution_target import build_plan_execution_target

RUN = "run-20261121-010"
NAMED = ["--item", "YOK-7", "--stage", "item-qa", "--deployment-run-id", RUN]


def _dispatched(command, args):
    with patch(
        "yoke_cli.commands.adapters.qa_execution_subjects.dispatch_and_emit",
        return_value=0,
    ) as dispatched:
        assert command(args) == 0
    return dispatched.call_args.kwargs


@pytest.mark.parametrize(
    ("command", "function_id"),
    [
        (qa_plan_materialize_for_item, "qa.plan.materialize"),
        (qa_plan_rematerialize, "qa.plan.rematerialize"),
    ],
)
def test_item_and_named_run_reach_the_handler(command, function_id):
    kwargs = _dispatched(command, [*NAMED, "--project", "yoke"])
    assert kwargs["function_id"] == function_id
    assert kwargs["target"].kind == "item"
    assert kwargs["target"].public_ref == "YOK-7"
    assert kwargs["payload"]["deployment_run_id"] == RUN
    assert kwargs["payload"]["deployment_stage"] == "item-qa"
    verify = kwargs["response_recovery"]
    answered = _response(function_id, {"result": {"deployment_run_id": "run-other"}})
    refused = verify(answered, None)
    assert not refused.success
    assert refused.error.code == "function_argument_version_skew"
    assert f"did not attest run {RUN}" in refused.error.message
    assert "minimum serving version next-release" in refused.error.message
    honoured = _response(function_id, {"result": {"deployment_run_id": RUN}})
    assert verify(honoured, None) is honoured


@pytest.mark.parametrize("command", [qa_plan_materialize_for_item, qa_plan_rematerialize])
def test_item_alone_sends_no_run(command):
    kwargs = _dispatched(command, ["--item", "YOK-7", "--stage", "item-qa"])
    assert "deployment_run_id" not in kwargs["payload"]
    assert "response_recovery" not in kwargs


@pytest.mark.parametrize("command", [qa_plan_materialize_for_item, qa_plan_rematerialize])
@pytest.mark.parametrize(
    "args",
    [
        ["--item", "YOK-7", "--transition", "release", "--deployment-run-id", RUN],
        ["--stage", "item-qa"],
    ],
)
def test_named_run_needs_a_stage_and_a_subject(command, args, capsys):
    with patch(
        "yoke_cli.commands.adapters.qa_execution_subjects.dispatch_and_emit"
    ) as dispatch:
        assert command(args) == 2
    dispatch.assert_not_called()


def test_plan_run_passes_item_and_named_run_together(capsys):
    with patch.object(
        qa_plan_execution_cli, "execute_plan", return_value={"state": "passed"}
    ) as execute:
        assert qa_plan_execution_cli.run([*NAMED, "--project", "yoke"]) == 0
    kwargs = execute.call_args.kwargs
    assert (kwargs["public_ref"], kwargs["deployment_run_id"]) == ("YOK-7", RUN)
    assert kwargs["deployment_stage"] == "item-qa"
    capsys.readouterr()


def test_plan_run_refuses_a_named_run_without_a_stage(capsys):
    with pytest.raises(SystemExit):
        qa_plan_execution_cli.run(
            ["--item", "YOK-7", "--transition", "release", "--deployment-run-id", RUN]
        )
    assert "requires --stage" in capsys.readouterr().err


def test_execution_target_carries_the_named_run_on_the_item():
    target, payload = build_plan_execution_target(
        public_ref="YOK-7", transition_id=None, deployment_run_id=RUN,
        deployment_stage="item-qa", deployment_member=None, plan=None, project="yoke",
    )
    assert target.kind == "item"
    assert payload == {"deployment_stage": "item-qa", "deployment_run_id": RUN}


def test_execution_refuses_a_receipt_for_another_run():
    require_selected_run("qa.plan_execution.begin", RUN, {"deployment_run_id": RUN})
    with pytest.raises(QaPlanExecutionError, match="function_argument_version_skew"):
        require_selected_run("qa.plan.materialize", RUN, {"result": {}})
    assert "receipt names no run" in selected_run_mismatch(
        "qa.plan_execution.begin", RUN, {}
    )


def _response(function_id, result):
    return FunctionCallResponse(
        success=True, function=function_id, version="v1", request_id="r", result=result
    )
