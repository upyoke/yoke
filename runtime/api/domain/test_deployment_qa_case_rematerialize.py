"""Refreshing an already-materialized deployment stage from its plan.

A materialized case is unique per subject and target, so a corrected plan
case cannot arrive as a second row under its own key. Refreshing an unjudged
case in place is the way through; how an answered sibling converges beside it
is covered in ``test_qa_plan_rematerialize_convergence``.
"""

from __future__ import annotations

from unittest import mock

import pytest

from runtime.api.fixtures.deployment_scoped_qa_run_fixture import (
    ITEM_QA_STAGE,
    seed_member_qa_case,
)
from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)
from yoke_core.domain.qa_plan_case_currency import STALE_PLAN_CASE_CODE
from yoke_core.domain.qa_plan_execution_state import begin_plan_execution
from yoke_core.domain.qa_plan_management import QaPlanError
from yoke_core.domain.qa_plan_refresh_safety import LIVE_EXECUTION_CODE
from yoke_core.domain.qa_plan_rematerialize_deployment import (
    rematerialize_for_deployment_stage,
)

MEMBER = 9811


def _seed(conn, run_id: str) -> int:
    return seed_member_qa_case(conn, run_id=run_id, member_item_id=MEMBER)


STAGE = ITEM_QA_STAGE


def _amend_plan_case(conn, requirement_id: int) -> None:
    plan_id = int(
        conn.execute(
            "SELECT plan_id FROM qa_requirements WHERE id=%s", (requirement_id,)
        ).fetchone()["plan_id"]
    )
    conn.execute(
        "UPDATE qa_plan_cases SET instructions=%s WHERE plan_id=%s",
        ("run the corrected smoke command", plan_id),
    )
    conn.commit()


def test_rematerialize_refreshes_an_unanswered_deployment_case(test_db) -> None:
    run_id = "run-rematerialize-open"
    requirement_id = _seed(test_db, run_id)
    _amend_plan_case(test_db, requirement_id)

    result = rematerialize_for_deployment_stage(
        test_db,
        deployment_run_id=run_id,
        deployment_stage=STAGE,
        deployment_member_item_id=MEMBER,
    )
    assert result["refreshed_requirement_ids"] == [requirement_id]
    row = test_db.execute(
        "SELECT instructions,execution_target_digest FROM qa_requirements WHERE id=%s",
        (requirement_id,),
    ).fetchone()
    assert str(row["instructions"]) == "run the corrected smoke command"
    # The frozen run keeps the target its stage receipt pinned.
    assert str(row["execution_target_digest"])


def test_rematerialize_refuses_a_subject_with_no_materialized_cases(test_db) -> None:
    run_id = "run-rematerialize-empty"
    requirement_id = _seed(test_db, run_id)
    test_db.execute("DELETE FROM qa_requirements WHERE id=%s", (requirement_id,))
    test_db.commit()
    with pytest.raises(QaPlanError, match="no materialized plan cases"):
        rematerialize_for_deployment_stage(
            test_db,
            deployment_run_id=run_id,
            deployment_stage=STAGE,
            deployment_member_item_id=MEMBER,
        )


def test_rematerialize_refuses_while_a_live_execution_walks_the_stage(
    test_db,
) -> None:
    """A walk in progress froze these rows; the refresh refuses before writing."""
    run_id = "run-rematerialize-walking"
    requirement_id = _seed(test_db, run_id)
    execution = begin_plan_execution(
        test_db,
        deployment_run_id=run_id,
        deployment_stage=STAGE,
        deployment_member_item_id=MEMBER,
        actor_id="op",
        session_id="session-walking",
    )
    _amend_plan_case(test_db, requirement_id)

    with pytest.raises(QaPlanError) as excinfo:
        rematerialize_for_deployment_stage(
            test_db,
            deployment_run_id=run_id,
            deployment_stage=STAGE,
            deployment_member_item_id=MEMBER,
        )

    message = str(excinfo.value)
    assert LIVE_EXECUTION_CODE in message
    assert f"--execution-id {execution['id']}" in message
    assert "yoke qa plan abort --deployment-run-id" in message
    # Refused before any write: the frozen body is exactly as the walk saw it.
    row = test_db.execute(
        "SELECT instructions FROM qa_requirements WHERE id=%s", (requirement_id,)
    ).fetchone()
    assert str(row["instructions"]) == "run the frozen smoke command"


def test_a_walk_refuses_an_unjudged_case_its_selected_plan_has_since_amended(
    test_db,
) -> None:
    """An unjudged row behind its selected plan never runs; the refusal
    names the refresh, and once refreshed the walk freezes the new body.

    The stage selects its plan at walk time, so the walk re-reads that plan:
    a failed row would be re-minted beside it, but a row nobody has judged
    still answers for the case and must be brought current instead.
    """
    from runtime.api.domain.test_deployment_qa_stage_execution import (
        _plan,
        _seed_run,
        _stages,
    )
    from yoke_core.domain.deployment_qa_stage_materialization import (
        materialize_deployment_qa_stage,
    )
    from yoke_core.domain.project_identity import render_item_ref
    from yoke_core.domain.qa_plan_management import replace_plan_cases

    run_id, member = "run-selected-plan-amended", 9895
    plan_id = _plan(test_db, "selected-amended-smoke")
    stages = _stages(plan_id)
    del stages[1]["cases"]
    _seed_run(test_db, run_id=run_id, stages=stages, members=(member,))
    subject = {
        "deployment_run_id": run_id,
        "deployment_stage": "item-qa",
        "deployment_member_item_id": member,
    }
    materialize_deployment_qa_stage(
        test_db, **subject, agent_plan="selected-amended-smoke"
    )
    corrected = {
        "case_key": "command-smoke",
        "position": 1,
        "method_id": "command",
        "instructions": "run the corrected smoke command",
        "expected_outcome": "the command passes",
        "method_config": {"command": "true --corrected"},
    }
    replace_plan_cases(test_db, plan_id=plan_id, cases=[corrected])
    test_db.commit()

    with pytest.raises(QaPlanError) as excinfo:
        materialize_deployment_qa_stage(
            test_db, **subject, agent_plan="selected-amended-smoke"
        )
    message = str(excinfo.value)
    assert STALE_PLAN_CASE_CODE in message
    assert (
        f"yoke qa plan rematerialize --deployment-run-id {run_id} --stage item-qa "
        f"--member {render_item_ref(test_db, member)}"
    ) in message

    rematerialize_for_deployment_stage(test_db, **subject)
    materialize_deployment_qa_stage(
        test_db, **subject, agent_plan="selected-amended-smoke"
    )
    execution = begin_plan_execution(
        test_db, **subject, actor_id="op", session_id="s-1"
    )
    assert [case["instructions"] for case in execution["roster"]] == [
        "run the corrected smoke command"
    ]


def _rematerialize_request(payload: dict) -> FunctionCallRequest:
    return FunctionCallRequest(
        function="qa.plan.rematerialize",
        actor=ActorContext(actor_id="1", session_id="run-qa-agent"),
        target=TargetRef(kind="deployment_run", deployment_run_id="run-recovery"),
        payload=payload,
    )


def test_run_scoped_rematerialize_is_authorized_by_the_run_not_an_item_claim(
    test_db,
) -> None:
    """The recovery qa.plan_cases.replace prints works for a run's QA agent.

    A run-scoped stage has no member, so an item claim cannot exist for it;
    the run itself authorizes the refresh, exactly as it authorizes the
    materialization being refreshed. A member stage still needs its claim.
    """
    from yoke_core.domain import yoke_function_registry
    from yoke_core.domain.handlers import __init_register__ as init_register
    from yoke_core.domain.yoke_function_dispatch_claims import verify_claim

    init_register.register_all_handlers()
    entry = yoke_function_registry.lookup("qa.plan.rematerialize")
    assert entry is not None and entry.claim_required_kind == "qa_subject"

    with mock.patch(
        "yoke_core.domain.qa_deployment_function_subject.resolve_run_qa_subject",
        return_value=(1, "yoke", None),
    ):
        refusal = verify_claim(
            entry, _rematerialize_request({"deployment_stage": "run-qa"})
        )
    assert refusal is None

    with (
        mock.patch(
            "yoke_core.domain.qa_deployment_function_subject.resolve_run_qa_subject",
            return_value=(1, "yoke", MEMBER),
        ),
        mock.patch(
            "yoke_core.domain.yoke_function_dispatch_claims.who_claims_for_item",
            return_value={"id": 5, "session_id": "another-session"},
        ),
    ):
        refusal = verify_claim(
            entry,
            _rematerialize_request(
                {"deployment_stage": STAGE, "deployment_member": str(MEMBER)}
            ),
        )
    assert refusal is not None and refusal.error is not None
    assert refusal.error.code == "claim_required"
