"""Unexecutable acceptance cases refuse before writing or copying."""

import pytest
from yoke_core.domain.handlers.qa_requirement_row_validation import validate_row
from yoke_core.domain.qa_requirement_proof import proof_refusal
from yoke_core.domain.deployment_qa_admission_materialization import (
    materialize_admitted_requirement,
)
from yoke_core.domain.qa_plan_management import QaPlanError


@pytest.mark.parametrize("source", ["explicit", "ac_derived"])
def test_blocking_acceptance_requires_executable_case(source):
    row = {
        "qa_kind": "ac_verification",
        "qa_phase": "verification",
        "requirement_source": source,
        "expected_outcome": "Visible output survives restart",
    }
    outcome = validate_row(row, "$.payload", subject="sample item")
    assert outcome.error.code == "requirement_proof_required"
    assert "sample item" in outcome.error.message
    assert "Visible output survives restart" in outcome.error.message
    assert "Attach the plan case" in outcome.error.message


@pytest.mark.parametrize(
    "kind", ["simulation", "implementation_review", "no_tests_declared"]
)
def test_real_domain_discharge_is_preserved(kind):
    assert not proof_refusal({"qa_kind": kind}, subject="sample")


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
        "INSERT INTO qa_requirements(item_id,qa_kind,qa_phase,blocking_mode,created_at) VALUES (2390,'ac_verification','verification','non_blocking',now()) RETURNING id"
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
