"""Unexecutable acceptance cases refuse before writing or copying."""

import pytest
from yoke_core.domain.qa_requirement_proof import proof_refusal
from yoke_core.domain.deployment_qa_admission_materialization import (
    materialize_admitted_requirement,
)
from yoke_core.domain.qa_plan_management import QaPlanError


@pytest.mark.parametrize("source", ["explicit", "ac_derived"])
def test_post_deploy_acceptance_requires_a_credit_path(source):
    row = {
        "qa_kind": "ac_verification",
        "qa_phase": "post_deploy",
        "workflow_transition_id": "release",
        "requirement_source": source,
        "expected_outcome": "Visible output survives restart",
    }
    refusal = proof_refusal(row, subject="sample item")
    assert "requirement_proof_required" in refusal
    assert "sample item" in refusal
    assert "Visible output survives restart" in refusal
    assert "Attach the plan case" in refusal


def test_reviewing_stage_acceptance_keeps_manual_credit(test_db):
    from runtime.api.fixtures.backlog_inserts import insert_item
    from yoke_core.domain.qa_workflow_binding_validation import item_transition_for_gate

    insert_item(test_db, id=2390, title="Reviewable acceptance", workflow_id="epic")
    transition = item_transition_for_gate(
        test_db, item_id=2390, gate_id="qa_verification"
    )
    assert not proof_refusal(
        {
            "qa_kind": "ac_verification",
            "qa_phase": "verification",
            "workflow_transition_id": transition,
        },
        subject="sample item",
        conn=test_db,
        item_id=2390,
    )


@pytest.mark.parametrize(
    "kind", ["simulation", "implementation_review", "no_tests_declared"]
)
def test_real_domain_discharge_is_preserved(kind, test_db):
    from runtime.api.fixtures.backlog_inserts import insert_item
    from yoke_core.domain.qa_workflow_binding_validation import item_transition_for_gate

    insert_item(test_db, id=2390, title="Domain verdict", workflow_id="epic")
    transition = item_transition_for_gate(
        test_db, item_id=2390, gate_id="qa_verification"
    )
    assert not proof_refusal(
        {
            "qa_kind": kind,
            "qa_phase": "verification",
            "workflow_transition_id": transition,
        },
        subject="sample",
        conn=test_db,
        item_id=2390,
    )


def test_nonblocking_and_method_cases_have_a_path():
    assert not proof_refusal(
        {"qa_kind": "ac_verification", "blocking_mode": "non_blocking"},
        subject="sample",
    )
    assert not proof_refusal({"method_id": "command"}, subject="sample")


def test_admission_refuses_copying_legacy_methodless_obligation():
    with pytest.raises(QaPlanError, match="requirement_proof_required.*requirement 17"):
        materialize_admitted_requirement(
            None,
            subject={"member_item_id": 2},
            requirement={"id": 17, "qa_kind": "ac_verification"},
            target={},
            now="",
        )


def test_advisory_legacy_row_cannot_become_blocking(test_db):
    from runtime.api.fixtures.backlog_inserts import insert_item
    from yoke_core.domain.qa_requirement_config_update import apply_requirement_update

    insert_item(test_db, id=2390, title="Historical advisory")
    rid = test_db.execute(
        "INSERT INTO qa_requirements(item_id,qa_kind,qa_phase,blocking_mode,created_at) VALUES (2390,'ac_verification','post_deploy','non_blocking',now()) RETURNING id"
    ).fetchone()[0]
    result = apply_requirement_update(test_db, rid, "blocking_mode", "blocking")
    assert not result.ok
    assert result.error_code == "requirement_proof_required"
    assert (
        test_db.execute(
            "SELECT blocking_mode FROM qa_requirements WHERE id=%s", (rid,)
        ).fetchone()[0]
        == "non_blocking"
    )


def test_typed_post_deploy_creation_refuses_uncreditable_derived_row(test_db):
    from runtime.api.fixtures.backlog_inserts import insert_item
    from runtime.api.test_api_qa_requirement_create_function import _request
    from yoke_core.domain.handlers.qa_requirement_create import (
        handle_qa_requirement_add,
    )

    insert_item(test_db, id=2390, title="Uncreditable acceptance", workflow_id="epic")
    test_db.commit()
    outcome = handle_qa_requirement_add(
        _request(
            "qa.requirement.add",
            2390,
            {
                "qa_kind": "ac_verification",
                "qa_phase": "post_deploy",
                "workflow_transition_id": "release",
                "requirement_source": "ac_derived",
                "expected_outcome": "Released behavior matches the criterion",
            },
        )
    )
    assert not outcome.primary_success
    assert outcome.error.code == "requirement_proof_required"
    assert "Released behavior matches the criterion" in outcome.error.message
    assert (
        test_db.execute(
            "SELECT count(*) FROM qa_requirements WHERE item_id=2390"
        ).fetchone()[0]
        == 0
    )
