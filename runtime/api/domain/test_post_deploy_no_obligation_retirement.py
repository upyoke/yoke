"""New blocking post-deploy work withdraws the item's earlier empty answer."""

from __future__ import annotations

import pytest

from runtime.api.fixtures.backlog_inserts import insert_item

from runtime.api.domain.test_post_deploy_no_obligation import (
    _handler_uses,
    _no_obligation_row,
    _record,
    _seed_item,
)
from runtime.api.domain.test_qa_plan_item_retract import (
    _attach_post_deploy,
    _materialize_item,
)
from yoke_core.domain.handlers.qa_requirement_create import (
    handle_qa_requirement_add,
    handle_qa_requirement_add_batch,
)
from yoke_core.domain.post_deploy_verification_answer import answer_for_item
from yoke_core.domain.qa_workflow_binding_validation import item_transition_for_gate
from yoke_core.domain.workflow_gate_catalog import GATE_QA_VERIFICATION
from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)

ITEM = 9901


def _declaration(conn, declaration_id):
    return conn.execute(
        "SELECT retracted_at,retraction_source,retraction_rationale,waived_at,"
        "instructions FROM qa_requirements WHERE id=%s",
        (declaration_id,),
    ).fetchone()


@pytest.mark.parametrize("batch", [False, True])
@pytest.mark.parametrize(
    "phase,mode,retires",
    [
        ("post_deploy", "blocking", True),
        ("post_deploy", "non_blocking", False),
        ("verification", "blocking", False),
    ],
)
def test_requirement_creation_retracts_only_for_blocking_post_deploy_work(
    test_db,
    batch,
    phase,
    mode,
    retires,
):
    insert_item(
        test_db,
        id=ITEM,
        project_sequence=901,
        workflow_id="issue",
        status="implementing",
    )
    test_db.commit()
    declaration_id = _no_obligation_row(test_db, ITEM, "internal types only")
    row = {
        "method_id": "command",
        "qa_phase": phase,
        "blocking_mode": mode,
        "workflow_transition_id": "release"
        if phase == "post_deploy"
        else item_transition_for_gate(
            test_db, item_id=ITEM, gate_id=GATE_QA_VERIFICATION
        ),
        "instructions": "Run the regression command.",
        "expected_outcome": "The command passes.",
        "method_config": {"command": "true"},
    }
    with _handler_uses(test_db):
        handler = (
            handle_qa_requirement_add_batch if batch else handle_qa_requirement_add
        )
        outcome = handler(
            FunctionCallRequest(
                function="qa.requirement.add_batch" if batch else "qa.requirement.add",
                actor=ActorContext(actor_id="op", session_id="s-1"),
                target=TargetRef(kind="item", item_id=ITEM),
                payload={"rows": [row]} if batch else row,
            )
        )
    assert outcome.primary_success, outcome.error
    declaration = _declaration(test_db, declaration_id)
    assert bool(declaration["retracted_at"]) is retires
    assert declaration["waived_at"] is None
    assert declaration["instructions"] == "internal types only"
    if retires:
        assert declaration["retraction_source"] == "blocking_post_deploy_requirement"
        assert "blocking post-deploy requirement" in declaration["retraction_rationale"]
        assert answer_for_item(test_db, ITEM).answered
        with _handler_uses(test_db):
            repeated = _record(ITEM, "try to reuse the withdrawn fact")
        assert not repeated.primary_success
        assert "already has post-deploy verification" in repeated.error.message


def test_materializing_post_deploy_plan_retracts_prior_no_obligation(test_db):
    _seed_item(test_db, item_id=ITEM, sequence=901)
    declaration_id = _no_obligation_row(test_db, ITEM, "docs only")
    _attach_post_deploy(test_db, item_id=ITEM, slug="post-deploy-real-work")
    materialized = _materialize_item(test_db, item_id=ITEM)
    assert materialized["created_requirement_ids"]
    first = dict(_declaration(test_db, declaration_id))
    assert first["retracted_at"]
    _materialize_item(test_db, item_id=ITEM)
    assert dict(_declaration(test_db, declaration_id)) == first


def test_failed_batch_rolls_back_no_obligation_retraction(test_db):
    _seed_item(test_db, item_id=ITEM, sequence=901)
    declaration_id = _no_obligation_row(test_db, ITEM, "docs only")
    row = {
        "qa_kind": "live_acceptance",
        "qa_phase": "post_deploy",
        "workflow_transition_id": "release",
    }
    with _handler_uses(test_db):
        outcome = handle_qa_requirement_add_batch(
            FunctionCallRequest(
                function="qa.requirement.add_batch",
                actor=ActorContext(actor_id="op", session_id="s-1"),
                target=TargetRef(kind="item", item_id=ITEM),
                payload={"rows": [row, {**row, "workflow_transition_id": "absent"}]},
            )
        )
    assert not outcome.primary_success
    assert _declaration(test_db, declaration_id)["retracted_at"] is None
    assert (
        test_db.execute(
            "SELECT count(*) FROM qa_requirements WHERE item_id=%s",
            (ITEM,),
        ).fetchone()[0]
        == 1
    )
