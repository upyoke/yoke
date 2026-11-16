"""``qa.plan_cases.replace`` refuses a case key it would otherwise drop.

PLAT-468's steering tried to set ``blocking_mode`` on a plan case through a
whole-case replacement; the key was silently dropped and the call reported
success. The handler now names the key and refuses before touching the plan.
"""

from unittest.mock import patch

from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)
from yoke_contracts.qa_plan_case_document import (
    QA_PLAN_CASE_FIELDS,
    unknown_case_field_refusal,
)
from yoke_core.domain.handlers import qa_plan_writes

CASE = {
    "case_key": "smoke",
    "position": 1,
    "method_id": "command",
    "instructions": "run it",
    "expected_outcome": "it works",
}


def _replace(cases):
    return qa_plan_writes.handle_plan_cases_replace(
        FunctionCallRequest(
            function="qa.plan_cases.replace",
            actor=ActorContext(actor_id="1", session_id="steering"),
            target=TargetRef(kind="global"),
            payload={"project": "example", "plan_id": 7, "cases": cases},
        )
    )


def test_replace_refuses_an_unknown_case_key_by_name():
    with patch("yoke_core.domain.db_helpers.connect") as connect:
        outcome = _replace([CASE, {**CASE, "case_key": "flag", "blocking_mode": "non_blocking"}])
    connect.assert_not_called()
    assert not outcome.primary_success
    assert outcome.error.code == "payload_invalid"
    assert outcome.error.jsonpath == "$.payload.cases"
    message = outcome.error.message
    assert message.startswith("qa_plan_case_field_unknown:")
    assert "flag: blocking_mode" in message
    assert "remove it and retry" in message


def test_known_case_fields_pass_the_check():
    assert unknown_case_field_refusal([CASE]) is None
    assert unknown_case_field_refusal([dict.fromkeys(QA_PLAN_CASE_FIELDS)]) is None


def test_unnamed_case_is_named_by_position():
    refusal = unknown_case_field_refusal([{"position": 1, "extra": 1}])
    assert refusal is not None and "case 1: extra" in refusal
