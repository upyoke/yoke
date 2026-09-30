"""Failed release QA reaches the member that can correct it."""

from __future__ import annotations

from typing import Any

import pytest

from yoke_contracts.hook_inline_context import INLINE_CONTEXT_BYTES
from yoke_core.hooks.session_message_delivery_port import (
    LeasedSessionMessage,
    SessionMessageLease,
)
from yoke_core.hooks.session_message_rendering import render_lease

from runtime.api.domain.test_deployment_qa_stage_execution import (
    _complete_case,
    _plan,
    _seed_run,
    _stages,
)
from runtime.api.domain.test_deployment_qa_stage_wake_delivery import (
    HOLDER_A,
    _bodies,
    _claim,
    _project,
    _recipients,
    seed_session,
)
from runtime.api.fixtures.backlog_inserts import (
    insert_item,
    insert_qa_requirement,
    insert_qa_run,
)
from yoke_core.domain.actor_permissions import ROLE_OWNER, grant_actor_project_role
from yoke_core.domain.deployment_qa_failure_handoff import (
    failure_handoff_key,
    notify_member_qa_failure,
)
from yoke_core.domain.deployment_qa_stage_gate import deployment_qa_stage_status
from yoke_core.domain.deployment_qa_stage_dispatch import (
    materialize_and_gate_deployment_qa_stage,
)
from yoke_core.domain.deployment_qa_stage_materialization import (
    materialize_deployment_qa_stage,
)
from yoke_core.domain.merge_queue_landing_notice import resolve_lane_recipient
from yoke_core.domain.qa_plan_execution_state import (
    advance_plan_execution,
    begin_plan_execution,
    finish_plan_execution,
)
from yoke_core.domain.work_claim_targets import make_item_target, make_steering_target


def _red_status(requirement_id: int) -> dict[str, Any]:
    return {
        "outcome": "blocked",
        "target_digest": "frozen-target",
        "case_failures": [{"requirement_id": requirement_id, "kind": "red"}],
    }


@pytest.mark.parametrize("producer", [HOLDER_A, "separate-qa-session"])
def test_failure_notice_is_inline_and_skips_its_verdict_producer(
    test_db: Any,
    producer: str,
) -> None:
    _project(test_db)
    member = 9901
    run_id = "run-member-qa-failure"
    _seed_run(
        test_db,
        run_id=run_id,
        stages=_stages(_plan(test_db, "member-qa-failure")),
        members=(member,),
    )
    seed_session(test_db, HOLDER_A)
    _claim(
        test_db,
        session_id=HOLDER_A,
        target_kind="item",
        scope_json=make_item_target(member).scope_json(),
    )
    materialize_deployment_qa_stage(
        test_db,
        deployment_run_id=run_id,
        deployment_stage="item-qa",
        deployment_member_item_id=member,
    )
    execution = begin_plan_execution(
        test_db,
        deployment_run_id=run_id,
        deployment_stage="item-qa",
        deployment_member_item_id=member,
        actor_id="2",
        session_id=producer,
    )
    requirement_id = int(execution["roster"][0]["requirement_id"])
    stamp = "2026-09-14T00:02:00Z"
    verdict_run_id = int(
        test_db.execute(
            "INSERT INTO qa_runs(qa_requirement_id,performed_by,qa_kind,verdict,"
            "started_at,completed_at,created_at) VALUES "
            "(%s,'worktree_run','plan_case','fail',%s,%s,%s) RETURNING id",
            (requirement_id, stamp, stamp, stamp),
        ).fetchone()[0]
    )
    advance_plan_execution(
        test_db,
        execution,
        ordinal=0,
        requirement_id=requirement_id,
        result={
            "requirement_id": requirement_id,
            "verdict": "fail",
            "case_outcome": "failed",
            "run_id": verdict_run_id,
        },
    )
    finish_plan_execution(test_db, execution, state="completed", reason="case failed")

    status = deployment_qa_stage_status(
        test_db, run_id=run_id, stage_name="item-qa", member_item_id=member
    )
    assert status["outcome"] == "blocked"
    key = failure_handoff_key(
        run_id, "item-qa", member, status["target_digest"], verdict_run_id
    )
    delivery = notify_member_qa_failure(
        test_db, run_id=run_id, stage="item-qa", item_id=member, status=status
    )
    if producer == HOLDER_A:
        assert delivery == ""
        assert _recipients(test_db, key) == []
        assert _bodies(test_db, key) == []
    else:
        assert delivery in {"delivered", "undelivered"}
        assert _recipients(test_db, key) == [HOLDER_A]
        [body] = _bodies(test_db, key)
        assert f"#{requirement_id}" in body
        assert run_id in body and "item-qa" in body
        assert "yoke qa plan run --help" in body
        assert "\n" not in body
        message_id = test_db.execute(
            "SELECT message_id FROM session_messages WHERE idempotency_key=%s", (key,)
        ).fetchone()[0]
        rendered, _ = render_lease(
            SessionMessageLease(
                lease_id="inline-notice",
                messages=(
                    LeasedSessionMessage(
                        message_id=str(message_id), body=body, sender_actor_id=2
                    ),
                ),
            ),
            session_id=HOLDER_A,
        )
        assert len(rendered.encode()) < min(INLINE_CONTEXT_BYTES.values())

    retry = begin_plan_execution(
        test_db,
        deployment_run_id=run_id,
        deployment_stage="item-qa",
        deployment_member_item_id=member,
        actor_id="2",
        session_id=HOLDER_A,
    )
    assert _complete_case(test_db, retry) == requirement_id
    assert deployment_qa_stage_status(
        test_db, run_id=run_id, stage_name="item-qa", member_item_id=member
    )["accepted"]
    assert (
        test_db.execute(
            "SELECT verdict FROM qa_runs WHERE id=%s", (verdict_run_id,)
        ).fetchone()[0]
        == "fail"
    )


def test_missing_holder_uses_member_project_steering_and_can_retry(
    test_db: Any,
) -> None:
    _project(test_db)
    member = 9902
    insert_item(test_db, id=member, project="other", project_sequence=member)
    other_project_id = int(
        test_db.execute(
            "SELECT project_id FROM items WHERE id=%s", (member,)
        ).fetchone()[0]
    )
    grant_actor_project_role(
        test_db, actor_id=2, project_id=other_project_id, role_name=ROLE_OWNER
    )
    requirement = insert_qa_requirement(test_db, item_id=member)
    verdict = insert_qa_run(
        test_db, qa_requirement_id=int(requirement["id"]), verdict="fail"
    )
    status = _red_status(int(requirement["id"]))
    key = failure_handoff_key(
        "run-cross-project", "item-qa", member, "frozen-target", int(verdict["id"])
    )
    first = notify_member_qa_failure(
        test_db,
        run_id="run-cross-project",
        stage="item-qa",
        item_id=member,
        status=status,
    )
    assert "unaddressed:" in first
    assert _recipients(test_db, key) == []

    seed_session(test_db, HOLDER_A, project_id=other_project_id)
    _claim(
        test_db,
        session_id=HOLDER_A,
        target_kind="steering",
        scope_json=make_steering_target(other_project_id).scope_json(),
    )
    assert (
        resolve_lane_recipient(test_db, item_id=member, project_id=other_project_id)[0]
        == HOLDER_A
    )
    assert notify_member_qa_failure(
        test_db,
        run_id="run-cross-project",
        stage="item-qa",
        item_id=member,
        status=status,
    ) in {"delivered", "undelivered"}
    assert _recipients(test_db, key) == [HOLDER_A]
    [body] = _bodies(test_db, key)
    assert "yoke qa plan run --help" in body
    assert f"#{requirement['id']}" in body


def test_run_recheck_reaches_a_holder_who_arrived_after_failure(test_db: Any) -> None:
    _project(test_db)
    member = 9903
    run_id = "run-late-member-holder"
    stages = _stages(_plan(test_db, "late-member-holder"))
    _seed_run(test_db, run_id=run_id, stages=stages, members=(member,))
    materialize_deployment_qa_stage(
        test_db,
        deployment_run_id=run_id,
        deployment_stage="item-qa",
        deployment_member_item_id=member,
    )
    requirement_id = int(
        test_db.execute(
            "SELECT id FROM qa_requirements WHERE deployment_run_id=%s "
            "AND deployment_member_item_id=%s AND method_id IS NOT NULL",
            (run_id, member),
        ).fetchone()[0]
    )
    failed = insert_qa_run(test_db, qa_requirement_id=requirement_id, verdict="fail")
    code, _reason = materialize_and_gate_deployment_qa_stage(
        test_db, stages[1], run_id=run_id
    )
    assert code == -4
    status = deployment_qa_stage_status(
        test_db, run_id=run_id, stage_name="item-qa", member_item_id=member
    )
    key = failure_handoff_key(
        run_id, "item-qa", member, status["target_digest"], int(failed["id"])
    )
    assert _recipients(test_db, key) == []

    seed_session(test_db, HOLDER_A)
    _claim(
        test_db,
        session_id=HOLDER_A,
        target_kind="item",
        scope_json=make_item_target(member).scope_json(),
    )
    code, _reason = materialize_and_gate_deployment_qa_stage(
        test_db, stages[1], run_id=run_id
    )
    assert code == -4
    assert _recipients(test_db, key) == [HOLDER_A]
