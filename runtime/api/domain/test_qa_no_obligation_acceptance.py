"""Informational aggregate rows cannot hold concrete deployment QA hostage."""

from __future__ import annotations

import json

import pytest

from runtime.api.domain.test_deployment_qa_case_discharge import (
    _acceptance,
    _execute_stage,
    _seed,
    _status,
    MEMBER,
    STAGE,
)
from yoke_core.domain.deployment_qa_stage_acceptance import STAGE_ACCEPTED
from yoke_core.domain.post_deploy_verification_answer import NO_OBLIGATION_QA_KIND


def _aggregate(conn, case_id, *, blocking):
    return int(
        conn.execute(
            "INSERT INTO qa_requirements(deployment_run_id,deployment_stage,"
            "deployment_member_item_id,qa_kind,qa_phase,blocking_mode,"
            "execution_target_json,execution_target_digest,created_at) "
            "SELECT deployment_run_id,deployment_stage,deployment_member_item_id,"
            "%s,'post_deploy',%s,execution_target_json,execution_target_digest,"
            "created_at FROM qa_requirements WHERE id=%s RETURNING id",
            (
                "visual_acceptance" if blocking else NO_OBLIGATION_QA_KIND,
                "blocking" if blocking else "non_blocking",
                case_id,
            ),
        ).fetchone()[0]
    )


@pytest.mark.parametrize("verdict", [None, "fail", "pass"])
def test_mixed_member_accepts_only_passing_evidence_linked_cases(test_db, verdict):
    run_id = f"run-mixed-no-obligation-{verdict or 'unrun'}"
    case_id = _seed(test_db, run_id)
    declaration_id = _aggregate(test_db, case_id, blocking=False)
    test_db.commit()
    if verdict is not None:
        _execute_stage(test_db, run_id, {case_id: verdict})
    status = _status(test_db, run_id)
    assert status["accepted"] is (verdict == "pass"), status["reasons"]
    acceptance = _acceptance(test_db, run_id)
    assert acceptance.accepted is (verdict == "pass")
    if verdict == "pass":
        assert acceptance.state == STAGE_ACCEPTED
        assert test_db.execute(
            "SELECT id FROM qa_requirements WHERE deployment_run_id=%s "
            "AND deployment_stage=%s AND deployment_member_item_id=%s "
            "AND qa_kind='deployment_stage_acceptance'",
            (run_id, STAGE, MEMBER),
        ).fetchone()
    assert (
        test_db.execute(
            "SELECT id FROM qa_runs WHERE qa_requirement_id=%s", (declaration_id,)
        ).fetchone()
        is None
    )


def test_blocking_aggregate_still_needs_explicit_evidence_linked_verdict(test_db):
    run_id = "run-mixed-blocking-aggregate"
    case_id = _seed(test_db, run_id)
    _aggregate(test_db, case_id, blocking=False)
    aggregate_id = _aggregate(test_db, case_id, blocking=True)
    test_db.commit()
    _execute_stage(test_db, run_id, {case_id: "pass"})
    status = _status(test_db, run_id)
    assert not status["accepted"]
    assert any(
        f"#{aggregate_id} has no explicit verdict" in r for r in status["reasons"]
    )
    execution_id = test_db.execute(
        "SELECT id FROM qa_plan_executions WHERE deployment_run_id=%s",
        (run_id,),
    ).fetchone()[0]
    artifact_id = int(
        test_db.execute(
            "SELECT a.id FROM qa_artifacts a JOIN qa_runs r ON r.id=a.qa_run_id "
            "WHERE r.qa_requirement_id=%s",
            (case_id,),
        ).fetchone()[0]
    )
    test_db.execute(
        "INSERT INTO qa_runs(qa_requirement_id,performed_by,qa_kind,verdict,"
        "raw_result,started_at,completed_at,created_at) "
        "VALUES (%s,'agent','visual_acceptance','pass',%s,%s,%s,%s)",
        (
            aggregate_id,
            json.dumps(
                {
                    "execution_id": execution_id,
                    "evidence_artifact_ids": [artifact_id],
                }
            ),
            *("2026-09-18T00:03:00Z",) * 3,
        ),
    )
    test_db.commit()
    assert _status(test_db, run_id)["accepted"]
