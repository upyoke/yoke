"""A case pass can settle a member without manufacturing a scoped walk."""

from runtime.api.fixtures.deployment_scoped_qa_run_fixture import (
    seed_member_qa_case,
    record_case_verdict,
)
from yoke_core.domain.deployment_qa_stage_gate import deployment_qa_stage_status
from yoke_core.domain.deployment_qa_stage_acceptance import stage_acceptance
from yoke_core.domain.deployment_qa_stage_contract import deployment_qa_stage_subject
from yoke_core.domain.deployment_qa_execution_target import (
    deployment_qa_execution_target,
)


def test_individual_case_pass_settles_member_without_execution(test_db):
    run_id, member = "run-direct-pass", 9845
    requirement = seed_member_qa_case(test_db, run_id=run_id, member_item_id=member)
    record_case_verdict(test_db, requirement, "pass", evidence=True)
    status = deployment_qa_stage_status(
        test_db, run_id=run_id, stage_name="item-qa", member_item_id=member
    )
    assert status["accepted"], status["reasons"]
    assert test_db.execute("SELECT COUNT(*) FROM qa_plan_executions").fetchone()[0] == 0
    subject = deployment_qa_stage_subject(
        test_db, run_id=run_id, stage_name="item-qa", member_item_id=member
    )
    assert stage_acceptance(
        test_db,
        subject=subject,
        target=deployment_qa_execution_target(test_db, subject),
        acceptance_qa_kind="deployment_stage_acceptance",
    ).accepted


def test_dispatcher_accepts_member_pass_without_scoped_walk(test_db):
    from yoke_core.domain.deployment_qa_stage_dispatch import (
        materialize_and_gate_deployment_qa_stage,
    )

    run_id, member = "run-dispatch-direct-pass", 9846
    requirement = seed_member_qa_case(test_db, run_id=run_id, member_item_id=member)
    record_case_verdict(test_db, requirement, "pass", evidence=True)
    code, message = materialize_and_gate_deployment_qa_stage(
        test_db, {"name": "item-qa", "scope": "item"}, run_id=run_id
    )
    assert code == 0, message
    assert test_db.execute("SELECT COUNT(*) FROM qa_plan_executions").fetchone()[0] == 0
