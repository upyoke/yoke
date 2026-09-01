"""Handler round-trip for amending a filed workflow-posture selection."""

from __future__ import annotations

import json

from runtime.api.fixtures.backlog_inserts import insert_item
from runtime.api.qa_catalog_test_support import CATALOG_CASES
from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)
from yoke_core.domain.handlers.workflows_item_posture import (
    handle_item_posture_amend,
)
from yoke_core.domain.qa_plan_management import create_plan, replace_plan_cases


def _request(item_id: int, payload: dict) -> FunctionCallRequest:
    return FunctionCallRequest(
        function="workflows.item_posture.amend",
        actor=ActorContext(actor_id="1", session_id="posture-amend-handler"),
        target=TargetRef(kind="item", item_id=item_id),
        payload=payload,
    )


def _dash(conn, *, item_id: int) -> int:
    row = insert_item(
        conn,
        id=item_id,
        workflow_id="dash",
        status="idea",
        workflow_posture=json.dumps({}),
    )
    conn.commit()
    return int(row["id"])


def test_handler_amends_through_the_dispatched_envelope(test_db) -> None:
    plan = create_plan(
        test_db, project="yoke", slug="amend-handler-plan", name="Amend handler"
    )
    replace_plan_cases(test_db, plan_id=plan["id"], cases=[CATALOG_CASES[0]])
    item_id = _dash(test_db, item_id=2810)

    outcome = handle_item_posture_amend(
        _request(
            item_id,
            {
                "key": "verification",
                "value": {"kind": "plan", "plan_id": int(plan["id"])},
                "reason": "selected through the function-call surface",
            },
        )
    )

    assert outcome.primary_success is True, outcome.error
    assert outcome.result_payload["changed"] is True
    assert outcome.result_payload["after"]["verification"] == {
        "kind": "plan",
        "plan_id": int(plan["id"]),
    }


def test_handler_reports_a_refusal_as_a_typed_error(test_db) -> None:
    item_id = _dash(test_db, item_id=2811)

    outcome = handle_item_posture_amend(
        _request(
            item_id,
            {"key": "approval", "value": True, "reason": "not a Dash key"},
        )
    )

    assert outcome.primary_success is False
    assert outcome.error.code == "incompatible"
    assert "does not allow posture key" in outcome.error.message
