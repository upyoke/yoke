"""A case that never started waits, and its line names the precondition's code.

Agent-mission dockets and host-control results record an unstarted case as
``blocked_on_precondition`` with no verdict, so the stage reads ``waiting``
rather than ``blocked``; the detail still names the run's error code and its
recovery, so a repair alarm is not hidden behind "waiting".
"""

from __future__ import annotations

import json

import pytest

from runtime.api.fixtures.deployment_scoped_qa_run_fixture import (
    ITEM_QA_STAGE,
    seed_member_qa_case,
)
from yoke_contracts.harness_provider_unavailable import PROVIDER_UNAVAILABLE_RECOVERY
from yoke_core.domain.deployment_qa_case_failure_kinds import FAILURE_UNRUN
from yoke_core.domain.deployment_qa_stage_gate import deployment_qa_stage_status
from yoke_core.domain.deployment_qa_stage_outcome import OUTCOME_WAITING

MEMBER = 9902
RESET = "yoke test-machine reset --test-machine lab --baseline fresh-host"


def _mission_docket(code: str, recovery: str) -> dict:
    failure = {"error_code": code, "recovery": recovery}
    return {
        "executor": "informed_subagent",
        "preparation": {
            "ok": False,
            "error_code": code,
            "evidence": {"preparation_failure": failure},
        },
    }


def _host_control(code: str, recovery: str) -> dict:
    return {
        "error_code": code,
        "evidence": {"case_started": False, "owed_reset": {"recovery": recovery}},
    }


def _record_blocked(conn, requirement_id: int, performed_by: str, raw: dict) -> None:
    """Record the unstarted run through the production write path."""
    from yoke_contracts.timestamps import parse_instant
    from yoke_core.domain.qa_requirement_pass_currency import (
        stamp_executed_method_config,
    )
    from yoke_core.domain.qa_run_verdict_record import insert_qa_run

    requirement = conn.execute(
        "SELECT method_config,execution_target_digest FROM qa_requirements WHERE id=%s",
        (requirement_id,),
    ).fetchone()
    now = parse_instant("2026-11-25T02:41:15Z")
    insert_qa_run(
        conn,
        qa_requirement_id=int(requirement_id),
        performed_by=performed_by,
        qa_kind="plan_case",
        execution_status="capture_failed",
        case_outcome="blocked_on_precondition",
        verdict=None,
        capture_degraded_reason=raw.get("error_code")
        or raw["preparation"]["error_code"],
        raw_result=stamp_executed_method_config(
            json.dumps(raw),
            requirement["method_config"],
            execution_target_digest=requirement["execution_target_digest"],
        ),
        started_at=now,
        completed_at=now,
        created_at=now,
    )
    conn.commit()


@pytest.mark.parametrize(
    "performed_by,shape", [("agent_mission", _mission_docket), ("host_control", _host_control)]
)
@pytest.mark.parametrize(
    "code,recovery",
    [
        ("harness_provider_unavailable", PROVIDER_UNAVAILABLE_RECOVERY),
        ("machine_needs_repair", RESET),
    ],
)
def test_unstarted_case_waits_and_names_its_code(
    test_db, performed_by, shape, code, recovery
):
    run_id = f"run-blocked-{performed_by}-{code}".replace("_", "-")
    requirement_id = seed_member_qa_case(test_db, run_id=run_id, member_item_id=MEMBER)
    _record_blocked(test_db, requirement_id, performed_by, shape(code, recovery))

    status = deployment_qa_stage_status(
        test_db, run_id=run_id, stage_name=ITEM_QA_STAGE, member_item_id=MEMBER
    )

    assert status["accepted"] is False
    assert status["outcome"] == OUTCOME_WAITING
    assert [failure["kind"] for failure in status["case_failures"]] == [FAILURE_UNRUN]
    detail = status["case_failures"][0]["detail"]
    assert f"blocked_on_precondition: {code}; {recovery}" in detail
