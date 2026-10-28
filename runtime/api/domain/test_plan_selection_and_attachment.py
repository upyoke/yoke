"""Plan selection and explicit phase attachments have separate obligations."""

import pytest

from runtime.api.domain.test_item_posture_amend import _dash, _plan, REVIEW
from runtime.api.fixtures.backlog_inserts import insert_qa_run
from yoke_core.domain.dash_posture_verification_gate import verification_gate
from yoke_core.domain.item_posture_bindings import bind_item_posture_selection
from yoke_core.domain.qa_plan_attachment_retract import retract_plan_from_item
from yoke_core.domain.qa_plan_attachments import (
    attach_plan_to_item,
    materialize_for_item,
)
from yoke_core.domain.qa_plan_management import QaPlanError


@pytest.mark.parametrize("commit", [True, False])
def test_plan_selection_never_attaches_or_creates_review_gate(test_db, commit):
    plan = _plan(test_db, "selection-only")
    selection = {"kind": "plan", "plan_id": plan["id"]}
    item_id = _dash(test_db, item_id=2850, posture={"verification": selection})
    assert bind_item_posture_selection(
        test_db,
        item_id=item_id,
        definition={},
        posture={"verification": selection},
        actor_id=None,
        commit=commit,
    ) == {"verification": None}
    assert (
        test_db.execute(
            "SELECT 1 FROM qa_plan_item_attachments WHERE item_id=%s", (item_id,)
        ).fetchone()
        is None
    )
    assert (
        verification_gate(
            test_db,
            item_id=item_id,
            verification=selection,
            target_status=REVIEW,
        )
        is None
    )
    attach_plan_to_item(
        test_db,
        item_id=item_id,
        plan_id=plan["id"],
        transition_id=REVIEW,
        qa_phase="verification",
    )
    assert (
        verification_gate(
            test_db,
            item_id=item_id,
            verification=selection,
            target_status=REVIEW,
        )["error_code"]
        == "GATE_DASH_VERIFICATION_REQUIRED"
    )
    retract_plan_from_item(
        test_db,
        item_id=item_id,
        plan_id=plan["id"],
        transition_id=REVIEW,
        reason="wrong review binding",
    )
    attach_plan_to_item(
        test_db,
        item_id=item_id,
        plan_id=plan["id"],
        transition_id="release",
        qa_phase="post_deploy",
    )
    materialize_for_item(test_db, item_id=item_id, transition_id="release")
    assert (
        verification_gate(
            test_db,
            item_id=item_id,
            verification=selection,
            target_status=REVIEW,
        )
        is None
    )
    assert (
        verification_gate(
            test_db,
            item_id=item_id,
            verification=selection,
            target_status="done",
        )["error_code"]
        == "GATE_DASH_VERIFICATION_UNSATISFIED"
    )


@pytest.mark.parametrize(
    "phase,transition",
    [
        ("verification", REVIEW),
        ("manual_acceptance", "done"),
    ],
)
@pytest.mark.parametrize("verdict", [None, "pending", "fail", "pass"])
def test_retraction_at_any_phase_requires_no_recorded_run(
    test_db, phase, transition, verdict
):
    plan = _plan(test_db, "retraction-before-run")
    item_id = _dash(
        test_db,
        item_id=2851,
        posture={
            "verification": {"kind": "plan", "plan_id": plan["id"]},
        },
    )
    attach_plan_to_item(
        test_db,
        item_id=item_id,
        plan_id=plan["id"],
        transition_id=transition,
        qa_phase=phase,
    )
    requirement_id = materialize_for_item(
        test_db,
        item_id=item_id,
        transition_id=transition,
    )["created_requirement_ids"][0]
    if verdict is not None:
        insert_qa_run(
            test_db,
            qa_requirement_id=requirement_id,
            verdict=None if verdict == "pending" else verdict,
        )
        with pytest.raises(QaPlanError, match="attachment_has_recorded_run"):
            retract_plan_from_item(
                test_db,
                item_id=item_id,
                plan_id=plan["id"],
                transition_id=transition,
                reason="wrong attachment",
            )
        assert (
            test_db.execute(
                "SELECT retracted_at FROM qa_requirements WHERE id=%s",
                (requirement_id,),
            ).fetchone()[0]
            is None
        )
    else:
        receipt = retract_plan_from_item(
            test_db,
            item_id=item_id,
            plan_id=plan["id"],
            transition_id=transition,
            reason="wrong attachment",
        )
        assert receipt["retired_requirement_ids"] == [requirement_id]
        assert (
            materialize_for_item(
                test_db,
                item_id=item_id,
                transition_id=transition,
            )["created_requirement_ids"]
            == []
        )
        assert (
            test_db.execute(
                "SELECT retracted_at FROM qa_requirements WHERE id=%s",
                (requirement_id,),
            ).fetchone()[0]
            is not None
        )


def test_post_deploy_attachment_writes_no_item_copy_and_retracts_freely(test_db):
    plan = _plan(test_db, "post-deploy-attachment")
    item_id = _dash(test_db, item_id=2852, posture={})
    attach_plan_to_item(
        test_db,
        item_id=item_id,
        plan_id=plan["id"],
        transition_id="release",
        qa_phase="post_deploy",
    )
    assert (
        materialize_for_item(test_db, item_id=item_id, transition_id="release")[
            "created_requirement_ids"
        ]
        == []
    )
    receipt = retract_plan_from_item(
        test_db,
        item_id=item_id,
        plan_id=plan["id"],
        transition_id="release",
        reason="wrong attachment",
    )
    assert receipt["retired_requirement_ids"] == []


def test_done_answers_a_post_deploy_selection_from_its_plan_group(test_db, monkeypatch):
    from yoke_core.domain import deployment_qa_plan_credit as credit

    plan = _plan(test_db, "post-deploy-selection")
    selection = {"kind": "plan", "plan_id": plan["id"]}
    item_id = _dash(test_db, item_id=2853, posture={"verification": selection})
    attach_plan_to_item(
        test_db,
        item_id=item_id,
        plan_id=plan["id"],
        transition_id="release",
        qa_phase="post_deploy",
    )
    miss = credit._miss(
        item_id, plan["id"], "post-deploy-selection", {"id": "run-x"}, "item-qa"
    )
    monkeypatch.setattr(credit, "plan_credit_misses", lambda conn, item: [miss])
    refused = verification_gate(
        test_db, item_id=item_id, verification=selection, target_status="done"
    )
    assert refused["error_code"] == "GATE_DASH_VERIFICATION_UNSATISFIED"
    assert "--plan post-deploy-selection" in str(refused)

    monkeypatch.setattr(credit, "plan_credit_misses", lambda conn, item: [])
    assert (
        verification_gate(
            test_db, item_id=item_id, verification=selection, target_status="done"
        )
        is None
    )
