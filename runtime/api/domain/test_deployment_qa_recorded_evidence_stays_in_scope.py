"""A live environment edit must not orphan recorded deployment QA evidence."""

from __future__ import annotations

import json

from runtime.api.domain.test_deployment_qa_stage_execution import _complete_case
from runtime.api.fixtures.deployment_scoped_qa_run_fixture import (
    ITEM_QA_STAGE,
    seed_member_qa_case,
)
from yoke_core.domain.deployment_qa_execution_target import (
    deployment_qa_execution_target,
)
from yoke_core.domain.deployment_qa_stage_case_failures import case_failures
from yoke_core.domain.deployment_qa_stage_contract import deployment_qa_stage_subject
from yoke_core.domain.deployment_qa_stage_gate import deployment_qa_stage_status
from yoke_core.domain.deployment_qa_stage_materialization import (
    materialize_deployment_qa_stage,
)
from yoke_core.domain.qa_execution_environment_target import target_digest
from yoke_core.domain.qa_plan_execution_state import begin_plan_execution

MEMBER = 9833


def _subject(conn, run_id: str):
    return deployment_qa_stage_subject(
        conn,
        run_id=run_id,
        stage_name=ITEM_QA_STAGE,
        member_item_id=MEMBER,
    )


def _move_environment_api_host(conn) -> None:
    conn.execute(
        "UPDATE environments SET settings=%s WHERE name=%s",
        (json.dumps({"hosts": {"api": "https://api.moved.example.test"}}), "stage"),
    )
    conn.commit()


def test_recorded_pass_stays_in_scope_when_environment_endpoints_move(test_db) -> None:
    run_id = "run-target-freeze-pass"
    requirement_id = seed_member_qa_case(
        test_db, run_id=run_id, member_item_id=MEMBER
    )
    original = deployment_qa_execution_target(test_db, _subject(test_db, run_id))
    original_digest = target_digest(original)
    execution = begin_plan_execution(
        test_db,
        deployment_run_id=run_id,
        deployment_stage=ITEM_QA_STAGE,
        deployment_member_item_id=MEMBER,
        actor_id="2",
        session_id="target-freeze",
    )
    _complete_case(test_db, execution)
    assert deployment_qa_stage_status(
        test_db, run_id=run_id, stage_name=ITEM_QA_STAGE, member_item_id=MEMBER
    )["accepted"]

    _move_environment_api_host(test_db)
    frozen = deployment_qa_execution_target(test_db, _subject(test_db, run_id))
    assert target_digest(frozen) == original_digest
    assert frozen["endpoints"]["api_url"] == original["endpoints"]["api_url"]
    assert deployment_qa_stage_status(
        test_db, run_id=run_id, stage_name=ITEM_QA_STAGE, member_item_id=MEMBER
    )["accepted"]

    again = materialize_deployment_qa_stage(
        test_db,
        deployment_run_id=run_id,
        deployment_stage=ITEM_QA_STAGE,
        deployment_member_item_id=MEMBER,
    )
    assert again["created_requirement_ids"] == []
    assert requirement_id in again["existing_requirement_ids"]
    count = test_db.execute(
        "SELECT COUNT(*) AS n FROM qa_requirements "
        "WHERE deployment_run_id=%s AND deployment_stage=%s "
        "AND deployment_member_item_id=%s AND method_id IS NOT NULL",
        (run_id, ITEM_QA_STAGE, MEMBER),
    ).fetchone()["n"]
    assert int(count) == 1


def test_out_of_scope_evidence_is_named_instead_of_reported_absent(test_db) -> None:
    run_id = "run-target-freeze-message"
    requirement_id = seed_member_qa_case(
        test_db, run_id=run_id, member_item_id=MEMBER
    )
    failures = case_failures(
        test_db,
        run_id=run_id,
        stage_name=ITEM_QA_STAGE,
        member_item_id=MEMBER,
        execution_target_digest="0" * 64,
    )
    assert len(failures) == 1
    detail = failures[0].detail
    assert "no concrete QA cases are materialized" not in detail
    assert f"#{requirement_id}" in detail
    assert "out of scope" in detail
    assert "do not rematerialize" in detail.lower()
