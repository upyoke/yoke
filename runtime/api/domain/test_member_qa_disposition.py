"""A discharged member says whether it owed item QA at all.

``discharged`` gates like a pass. The recorded no-obligation answer and a
waiver both reach it, and the delivery card must not call either a pass or
call them the same thing, so the standing names the no-obligation case.
"""

from __future__ import annotations

from runtime.api.domain.test_deployment_qa_member_acceptance_notice import (
    _executing_run,
)
from runtime.api.domain.test_no_obligation_member_close_out import (
    _declared_none,
    _no_obligation,
)
from yoke_core.domain.deployment_qa_run_acceptance import member_qa_standings

NO_QA_MEMBER = 9841
WAIVED_MEMBER = 9842
RUN_ID = "run-qa-disposition"


def test_no_obligation_and_waiver_are_distinct_discharges(test_db) -> None:
    _executing_run(
        test_db, RUN_ID, (NO_QA_MEMBER, WAIVED_MEMBER), plan_slug="disposition"
    )
    _no_obligation(test_db, NO_QA_MEMBER, reason="nothing observable once deployed")
    _declared_none(test_db, WAIVED_MEMBER)
    test_db.commit()

    standings = member_qa_standings(
        test_db,
        [(RUN_ID, NO_QA_MEMBER, "item-qa"), (RUN_ID, WAIVED_MEMBER, "item-qa")],
    )

    no_qa = standings[(RUN_ID, NO_QA_MEMBER)]
    waived = standings[(RUN_ID, WAIVED_MEMBER)]
    assert (no_qa["state"], no_qa["no_item_qa_required"]) == ("discharged", True)
    assert (waived["state"], waived["no_item_qa_required"]) == ("discharged", False)



def test_item_delivery_read_carries_its_completion_run_standing(test_db) -> None:
    from runtime.api.domain.test_independent_member_delivery_close_out import (
        MEMBER_A,
        _seed_final_run,
    )
    from yoke_contracts.api.function_call import (
        ActorContext,
        FunctionCallRequest,
        TargetRef,
    )
    from yoke_core.domain.handlers.deployment_inspection import (
        handle_deployment_runs_find_by_item,
    )

    _seed_final_run(test_db, "run-delivery-read", shared_qa=False)
    _no_obligation(test_db, MEMBER_A, reason="nothing observable once deployed")
    test_db.commit()

    found = handle_deployment_runs_find_by_item(
        FunctionCallRequest(
            function="deployment_runs.find_by_item",
            actor=ActorContext(session_id="test-session"),
            target=TargetRef(kind="item", item_id=MEMBER_A),
            payload={},
        )
    )

    assert found.result_payload["completion_run"]["id"] == "run-delivery-read"
    standing = found.result_payload["completion_item_qa"]
    assert standing["state"] == "discharged"
    assert standing["no_item_qa_required"] is True
    assert standing["settling"] is False
