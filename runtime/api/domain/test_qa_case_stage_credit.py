"""Case-run must name the plan-run that would credit an item-scoped stage.

A passing `yoke qa case run` verdict does not satisfy a deployment stage.
The defect is silence: the command exits zero, so a worker reports the gate
done. These tests lock the opposite — the output names the exact plan-run
invocation, and an ordinary unbound case still produces no such message.
"""

from __future__ import annotations

from yoke_core.domain.qa_case_stage_credit import (
    item_scoped_stage_credit_refusal,
    item_scoped_stage_plan_run_command,
)

RUN_ID = "run-20260101-001"
STAGE = "item-qa"
MEMBER_ID = 3454
MEMBER_REF = "YOK-42"
PROJECT = "yoke"

PLAN_RUN = (
    f"yoke qa plan run --deployment-run-id {RUN_ID} --stage {STAGE} "
    f"--member {MEMBER_REF} --project {PROJECT}"
)


def _item_scoped_case(**overrides):
    case = {
        "requirement_id": 28924,
        "deployment_run_id": RUN_ID,
        "deployment_stage": STAGE,
        "deployment_member_item_id": MEMBER_ID,
        "deployment_member_ref": MEMBER_REF,
        "project": PROJECT,
    }
    case.update(overrides)
    return case


def test_plan_run_command_names_run_stage_member_and_project() -> None:
    assert item_scoped_stage_plan_run_command(_item_scoped_case()) == PLAN_RUN


def test_item_scoped_binding_names_the_plan_run_that_would_credit_the_stage() -> None:
    message = item_scoped_stage_credit_refusal(_item_scoped_case())
    assert message is not None
    assert "STAGE CREDIT REFUSAL" in message
    assert STAGE in message
    assert MEMBER_REF in message
    assert PLAN_RUN in message


def test_ordinary_item_case_is_silent() -> None:
    assert (
        item_scoped_stage_credit_refusal(
            {
                "requirement_id": 12,
                "item_id": 99,
                "project": PROJECT,
            }
        )
        is None
    )


def test_run_scoped_stage_without_a_member_is_not_this_refusal() -> None:
    assert (
        item_scoped_stage_credit_refusal(
            _item_scoped_case(
                deployment_member_item_id=None,
                deployment_member_ref=None,
            )
        )
        is None
    )


def test_missing_binding_fields_degrade_to_prior_silence() -> None:
    """An older case contract without these keys must not refuse."""
    assert item_scoped_stage_credit_refusal({"requirement_id": 12}) is None
