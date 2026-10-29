"""Direct member case runs execute and can settle their deployment stage."""

from __future__ import annotations

from unittest import mock

from yoke_core.domain import qa_case_execution, qa_case_execution_cli

RUN_ID = "run-20260101-001"
STAGE = "item-qa"
MEMBER_REF = "YOK-42"
PROJECT = "yoke"
PLAN_RUN = f"yoke qa plan run --item {MEMBER_REF} --stage {STAGE} --project {PROJECT}"

ITEM_SCOPED_CASE = {
    "requirement_id": 41,
    "deployment_run_id": RUN_ID,
    "deployment_stage": STAGE,
    "deployment_member_item_id": 3454,
    "deployment_member_ref": MEMBER_REF,
    "project": PROJECT,
}

ORDINARY_CASE = {
    "requirement_id": 41,
    "item_id": 9,
    "project": PROJECT,
}


def test_case_run_executes_item_scoped_binding(capsys) -> None:
    with (
        mock.patch.object(
            qa_case_execution,
            "fetch_case_execution_context",
            return_value=ITEM_SCOPED_CASE,
        ),
        mock.patch.object(
            qa_case_execution,
            "execute_case_context",
            return_value={"requirement_id": 41, "verdict": "pass", "run_id": 7},
        ) as execute,
    ):
        code = qa_case_execution_cli.run(
            ["--requirement-id", "41", "--session-id", "case-session"]
        )

    captured = capsys.readouterr()
    output = captured.out + captured.err
    assert code == 0
    assert "STAGE CREDIT REFUSAL" not in output
    execute.assert_called_once()


def test_ordinary_case_run_still_executes_and_exits_zero(capsys) -> None:
    with (
        mock.patch.object(
            qa_case_execution,
            "fetch_case_execution_context",
            return_value=ORDINARY_CASE,
        ),
        mock.patch.object(
            qa_case_execution,
            "execute_case_context",
            return_value={"requirement_id": 41, "verdict": "pass", "run_id": 7},
        ) as execute,
    ):
        code = qa_case_execution_cli.run(
            ["--requirement-id", "41", "--session-id", "case-session"]
        )

    captured = capsys.readouterr()
    output = captured.out + captured.err
    assert code == 0
    assert "STAGE CREDIT REFUSAL" not in output
    execute.assert_called_once()
