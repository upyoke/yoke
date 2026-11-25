"""A refused member close-out retries when the record blocking it settles.

The member's item QA is accepted on its executing run, but its own capture
has no verdict, so the done write refuses. The refusal notice names that
record. Settling it — a verdict through its ordinary write, or a waiver
through the follow-up it owes the background replay — re-runs the same
close-out, and the member reaches done without a re-drive.
"""

from __future__ import annotations

import json
from typing import Any
from uuid import uuid4

import pytest

from runtime.api.domain.independent_member_delivery_close_out_test_support import (
    MEMBER_A,
    MEMBER_B,
    _seed_final_run,
    _settle,
    _status,
)
from runtime.api.domain import independent_member_delivery_close_out_test_support
from runtime.api.domain.deployment_qa_stage_wake_delivery_test_support import HOLDER_A
from runtime.api.domain.qa_host_turns_test_support import MACHINE, _notices
from runtime.api.domain.status_transition_preflight_test_support import (
    _isolate_status_effects,
)
from runtime.api.domain.test_deployment_qa_stage_human_review import _agent_review_plan
from runtime.api.fixtures.backlog import insert_qa_requirement, insert_qa_run
from runtime.api.fixtures.deployment_run_driver_fixture import release_seeded_driver
from runtime.api.fixtures.deployment_scoped_qa_run_fixture import (
    record_case_verdict,
    seed_member_qa_case,
)
from runtime.api.domain.qa_verdict_citation_test_support import cite_case

from yoke_contracts.api.function_call import ActorContext, FunctionCallRequest, TargetRef
from yoke_core.domain.coordination_claims import active_claim
from yoke_core.domain.deployment_member_close_out_retry import (
    after_record_settled,
    retry_member_close_out,
)
from yoke_core.domain.deployment_qa_member_acceptance_notice import (
    item_qa_accepted_idempotency_key,
)
from yoke_core.domain.deployment_qa_stage_materialization import (
    materialize_deployment_qa_stage,
)
from yoke_core.domain.handlers.qa_plan_execution import (
    handle_plan_execution_advance,
    handle_plan_execution_complete,
)
from yoke_core.domain.qa_plan_execution_state import advance_plan_execution, begin_plan_execution
from yoke_core.domain.qa_host_set_turns import execution_waits, record_host_wait
from yoke_core.domain.qa_host_turns import join_host_queue
from yoke_core.domain.qa_plan_execution_store import lock_plan_execution, roster_digest
from yoke_core.domain.qa_plan_review import begin_plan_review
from yoke_core.domain.qa_plan_review_submission import submit_plan_review
from yoke_core.domain.qa_requirement_ops import waive_requirement
from yoke_core.domain.qa_requirement_pass_currency import stamp_executed_method_config
from yoke_core.domain.qa_settlement_followups import replay_settlement_followups
from yoke_core.domain.qa_run_execution_evidence import commit_settled_verdict
from yoke_core.domain.qa_run_verdict_record import update_qa_run
from yoke_core.domain.work_claim_targets import make_item_target, make_qa_admission_target

RUN_ID = "run-close-out-retry"


def _row_id(row: Any) -> int:
    return int(row["id"] if hasattr(row, "keys") else row[0])


def _blocked_member(conn: Any) -> tuple[int, int]:
    """MEMBER_A's QA is accepted, but its own capture still owes a verdict."""
    _seed_final_run(conn, RUN_ID, shared_qa=False)
    requirement_id = _row_id(
        insert_qa_requirement(conn, item_id=MEMBER_A, blocking_mode="non_blocking")
    )
    capture_id = _row_id(
        insert_qa_run(
            conn,
            qa_requirement_id=requirement_id,
            verdict=None,
            execution_status="captured",
        )
    )
    conn.commit()
    _settle(conn, run_id=RUN_ID, stage="item-qa", member=MEMBER_A)
    return requirement_id, capture_id


def _refusal_bodies(conn: Any, item_id: int) -> list[str]:
    key = item_qa_accepted_idempotency_key(item_id, RUN_ID) + ":blocked:%"
    rows = conn.execute(
        "SELECT body FROM session_messages WHERE idempotency_key LIKE %s ORDER BY 1",
        (key,),
    ).fetchall()
    return [row["body"] for row in rows]


def test_the_refusal_notice_names_the_blocking_record(test_db, monkeypatch) -> None:
    _isolate_status_effects(monkeypatch)
    _requirement_id, capture_id = _blocked_member(test_db)

    assert _status(test_db, MEMBER_A) == "release"
    [body] = _refusal_bodies(test_db, MEMBER_A)
    assert "Automatic close-out failed" in body
    assert f"  - run #{capture_id}:" in body


@pytest.mark.parametrize("settle", ["verdict", "waiver"])
def test_settling_the_blocker_closes_the_member(test_db, monkeypatch, settle) -> None:
    _isolate_status_effects(monkeypatch)
    requirement_id, capture_id = _blocked_member(test_db)

    if settle == "verdict":
        update_qa_run(test_db, capture_id, {"verdict": "pass", "verdict_reason": "ok"})
        commit_settled_verdict(test_db, capture_id)
    else:
        waive_requirement(test_db, requirement_id, "not needed here", force=True)
        # The waive answers before the close-out; the queue worker runs it.
        assert _status(test_db, MEMBER_A) == "release"
        assert replay_settlement_followups(test_db)["replayed"] == [MEMBER_A]

    assert _status(test_db, MEMBER_A) == "done"
    assert _status(test_db, MEMBER_B) == "release"


def test_final_waiver_releases_reserved_turn_and_settles_member(test_db, monkeypatch):
    from runtime.api.domain.deployment_qa_stage_wake_delivery_test_support import HOLDER_B

    _isolate_status_effects(monkeypatch)
    _seed_final_run(test_db, RUN_ID, shared_qa=False)
    _notices(monkeypatch)
    requirements = [
        _row_id(insert_qa_requirement(test_db, item_id=MEMBER_A, blocking_mode="non_blocking"))
        for _ in range(3)
    ]
    roster = [{"requirement_id": requirement} for requirement in requirements]
    execution = str(uuid4())
    test_db.execute(
        "INSERT INTO qa_plan_executions(id,item_id,transition_id,session_id,actor_id,"
        "roster_digest,roster_json,cursor_ordinal,state,created_at,heartbeat_at) "
        "VALUES(%s,%s,'release',%s,'1',%s,%s,1,'active',now(),now())",
        (execution, MEMBER_A, HOLDER_A, roster_digest(roster), json.dumps(roster)),
    )
    record_host_wait(
        test_db, lock_plan_execution(test_db, execution), test_machine=MACHINE, rationale="test queue"
    )
    target = make_qa_admission_target(MACHINE)
    reservation = active_claim(test_db, target)
    assert reservation.session_id == HOLDER_A
    join_host_queue(test_db, target, session_id=HOLDER_B, actor_id=1, resume_command="manual acquire")
    test_db.commit()
    _settle(test_db, run_id=RUN_ID, stage="item-qa", member=MEMBER_A)
    assert _status(test_db, MEMBER_A) == "release"

    waive_requirement(test_db, requirements[1], "no longer needed")
    assert lock_plan_execution(test_db, execution)["state"] == "waiting"
    assert execution_waits(test_db, execution)[0]["state"] == "reserved"
    assert active_claim(test_db, target).id == reservation.id
    test_db.commit()

    waive_requirement(test_db, requirements[2], "no longer needed")
    stopped = lock_plan_execution(test_db, execution)
    assert stopped["state"] == "aborted"
    assert stopped["release_reason"] == (
        f"qa_requirement_waived: requirement {requirements[2]} was waived; nothing left to walk"
    )
    assert not execution_waits(test_db, execution)
    assert active_claim(test_db, target).session_id == HOLDER_B
    test_db.commit()
    assert replay_settlement_followups(test_db)["replayed"] == [MEMBER_A]
    assert _status(test_db, MEMBER_A) == "done"


def test_a_member_its_run_has_not_accepted_is_left_to_its_stage(
    test_db, monkeypatch
) -> None:
    _isolate_status_effects(monkeypatch)
    _blocked_member(test_db)

    assert retry_member_close_out(test_db, item_id=MEMBER_B) == []
    after_record_settled(test_db, item_id=MEMBER_B)
    assert _status(test_db, MEMBER_B) == "release"
    assert _refusal_bodies(test_db, MEMBER_B) == []


def _run_status(conn, run_id):
    return conn.execute(
        "SELECT status FROM deployment_runs WHERE id=%s", (run_id,)
    ).fetchone()["status"]


def test_owner_review_closes_accepted_member_while_a_sibling_waits(
    test_db, monkeypatch, capsys
):
    _isolate_status_effects(monkeypatch)
    monkeypatch.setattr(
        independent_member_delivery_close_out_test_support,
        "_plan",
        lambda conn, _slug: _agent_review_plan(conn),
    )
    _seed_final_run(test_db, RUN_ID, shared_qa=False)
    for member in (MEMBER_A, MEMBER_B):
        materialize_deployment_qa_stage(
            test_db,
            deployment_run_id=RUN_ID,
            deployment_stage="item-qa",
            deployment_member_item_id=member,
        )
    execution = begin_plan_execution(
        test_db,
        deployment_run_id=RUN_ID,
        deployment_stage="item-qa",
        deployment_member_item_id=MEMBER_A,
        actor_id="1",
        session_id=HOLDER_A,
    )
    case = execution["roster"][0]
    requirement_id = case["requirement_id"]
    raw = stamp_executed_method_config(
        None, case["method_config"], execution_target_digest=execution["execution_target_digest"]
    )
    capture_id = test_db.execute(
        "INSERT INTO qa_runs(qa_requirement_id,performed_by,qa_kind,case_outcome,"
        "raw_result,created_at,started_at,completed_at) VALUES "
        "(%s,'browser_substrate','plan_case','needs_review',%s,NOW(),NOW(),NOW()) "
        "RETURNING id",
        (requirement_id, raw),
    ).fetchone()["id"]
    test_db.execute(
        "INSERT INTO qa_artifacts(qa_run_id,artifact_type,artifact_handle,created_at) "
        "VALUES (%s,'screenshot','evidence://reviewed-release',NOW())",
        (capture_id,),
    )
    advance_plan_execution(
        test_db, execution, ordinal=0, requirement_id=requirement_id,
        result={"qa_run_id": capture_id, "case_outcome": "needs_review"},
    )
    bundle = begin_plan_review(test_db, execution)
    result = submit_plan_review(
        test_db,
        execution,
        bundle_id=bundle["bundle_id"],
        bundle_digest=bundle["bundle_digest"],
        verdicts=[{
            "requirement_id": requirement_id,
            "verdict": "pass",
            "rationale": cite_case(bundle, "The captured release has the expected content."),
        }],
        reviewer_actor_id="1",
        reviewer_session_id=HOLDER_A,
    )
    assert result["state"] == "passed"
    assert _status(test_db, MEMBER_A) == "done"
    assert active_claim(test_db, make_item_target(MEMBER_A)) is None
    assert "post-deploy obligations satisfied" in capsys.readouterr().out
    assert _status(test_db, MEMBER_B) == "release"
    assert _run_status(test_db, RUN_ID) == "executing"


@pytest.mark.parametrize("binding", ["none", "own", "other"])
def test_verdict_defers_only_to_its_own_open_execution(test_db, monkeypatch, binding):
    _isolate_status_effects(monkeypatch)
    requirement_id = seed_member_qa_case(test_db, run_id=RUN_ID, member_item_id=MEMBER_A)
    release_seeded_driver(test_db, RUN_ID)
    actor = ActorContext(actor_id="1", session_id=HOLDER_A)

    def begin():
        return begin_plan_execution(
            test_db,
            deployment_run_id=RUN_ID,
            deployment_stage="item-qa",
            deployment_member_item_id=MEMBER_A,
            actor_id=actor.actor_id,
            session_id=actor.session_id,
        )

    if binding != "none":
        execution = begin()
    if binding == "other":
        # Model an independent verdict with no link to the live plan execution.
        raw = stamp_executed_method_config(
            None, execution["roster"][0]["method_config"],
            execution_target_digest=execution["execution_target_digest"],
        )
        run_id = _row_id(insert_qa_run(
            test_db, qa_requirement_id=requirement_id, raw_result=raw, qa_kind="plan_case",
        ))
        test_db.execute(
            "INSERT INTO qa_artifacts(qa_run_id,artifact_type,artifact_handle,created_at) "
            "VALUES (%s,'log','evidence://independent-case',NOW())",
            (run_id,),
        )
    else:
        run_id = record_case_verdict(test_db, requirement_id, "pass", evidence=True)
    raw = test_db.execute("SELECT raw_result FROM qa_runs WHERE id=%s", (run_id,)).fetchone()[0]
    assert bool(json.loads(raw).get("execution_id")) == (binding == "own")
    commit_settled_verdict(test_db, run_id)

    if binding == "own":
        assert _run_status(test_db, RUN_ID) == "executing"
        advance = handle_plan_execution_advance(FunctionCallRequest(
            function="qa.plan_execution.advance",
            actor=actor,
            target=TargetRef(kind="item", item_id=MEMBER_A),
            payload={
                "execution_id": execution["id"],
                "ordinal": 0,
                "requirement_id": requirement_id,
                "result": {"run_id": run_id, "verdict": "pass", "case_outcome": "passed"},
            },
        ))
        assert advance.primary_success, advance.error
        complete = handle_plan_execution_complete(FunctionCallRequest(
            function="qa.plan_execution.complete",
            actor=actor,
            target=TargetRef(kind="item", item_id=MEMBER_A),
            payload={"execution_id": execution["id"]},
        ))
        assert complete.primary_success, complete.error
    assert _run_status(test_db, RUN_ID) == "succeeded"
