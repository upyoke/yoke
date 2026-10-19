"""A deployment pass answers only its own standing obligation."""

import pytest
from runtime.api.domain.test_dash_post_deploy_review_isolation import _insert_dash
from runtime.api.fixtures.deployment_admitted_case_fixture import (
    deliver_with_failing_admitted_copy,
)
from runtime.api.fixtures.deployment_scoped_qa_run_fixture import record_case_verdict
from yoke_core.domain.qa_requirement_supersession import record_supersession, same_scope
from yoke_core.domain.qa_requirement_run_proof import run_proof_mismatches


def _source():
    return dict(
        id=5,
        item_id=2,
        plan_id=3,
        plan_case_key="visible-output",
        method_id="command",
        qa_phase="post_deploy",
        target_env="prod",
    )


def _answer():
    return dict(
        deployment_run_id="sample",
        deployment_member_item_id=2,
        plan_id=3,
        plan_case_key="visible-output",
        method_id="command",
        qa_phase="post_deploy",
        target_env="prod",
    )


def test_same_plan_case_can_answer_across_scopes():
    assert same_scope(_source(), _answer()) == []


@pytest.mark.parametrize(
    "field,value",
    [
        ("plan_id", 4),
        ("plan_case_key", "other"),
        ("deployment_member_item_id", 9),
        ("target_env", "stage"),
        ("host_baseline", "other"),
        ("method_id", "other"),
    ],
)
def test_other_obligations_cannot_discharge_standing_case(field, value):
    assert run_proof_mismatches(_source(), dict(_answer(), **{field: value}))


def test_run_scoped_pass_supersedes_direct_standing_source(test_db):
    _insert_dash(test_db, item_id=2390, status="release")
    source, copy, _ = deliver_with_failing_admitted_copy(
        test_db, item_id=2390, run_id="run-standing-proof", corrected=False
    )
    record_case_verdict(test_db, copy, "pass", evidence=True)
    receipt, _ = record_supersession(
        test_db,
        requirement_id=source,
        superseded_by_requirement_id=copy,
        rationale="Frozen copy proves the standing case",
    )
    assert receipt["superseded_by_requirement_id"] == copy
