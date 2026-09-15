"""A human verdict on a deployment QA stage reaches the agent that parked.

Driven through the real decision-resolution path against a real
database: the stage opens its own review request, a reviewer resolves it,
and the message the parked agent needs has to exist afterwards. A
rejection is the case that matters most — that is when the agent has
work to do — so it is covered alongside the approval rather than assumed
to behave the same way.
"""

from __future__ import annotations

from typing import Any

from runtime.api.fixtures.backlog_inserts import insert_item
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
from yoke_core.domain.decision_request_resolution import resolve_decision_request
from yoke_core.domain.deployment_qa_stage_gate import deployment_qa_stage_status
from yoke_core.domain.deployment_qa_stage_materialization import (
    materialize_deployment_qa_stage,
)
from yoke_core.domain.deployment_qa_verdict_notice import verdict_idempotency_key
from yoke_core.domain.qa_plan_execution_state import begin_plan_execution
from yoke_core.domain.work_claim_targets import make_item_target

REVIEWER = 9797


def _human_actor(conn: Any, actor_id: int) -> None:
    conn.execute(
        "INSERT INTO actors(id,kind,created_at) VALUES "
        "(%s,'human','2026-09-14T00:00:00Z') ON CONFLICT(id) DO NOTHING",
        (actor_id,),
    )


def _awaiting_review(conn: Any, *, run_id: str, member: int, slug: str) -> int:
    """Take one item-scoped stage all the way to its open review request."""
    plan_id = _plan(conn, slug)
    stages = _stages(
        plan_id,
        verdict={
            "mode": "required_human",
            "reviewers": {"mode": "all", "roles": [], "actors": [REVIEWER]},
        },
    )
    _seed_run(conn, run_id=run_id, stages=stages, members=(member,))
    materialize_deployment_qa_stage(
        conn,
        deployment_run_id=run_id,
        deployment_stage="item-qa",
        deployment_member_item_id=member,
    )
    execution = begin_plan_execution(
        conn,
        deployment_run_id=run_id,
        deployment_stage="item-qa",
        deployment_member_item_id=member,
        actor_id="2",
        session_id="member-qa",
    )
    _complete_case(conn, execution)
    pending = deployment_qa_stage_status(
        conn, run_id=run_id, stage_name="item-qa", member_item_id=member
    )
    assert not pending["accepted"]
    assert pending["request_id"] is not None
    return int(pending["request_id"])


def _hold_the_item(conn: Any, member: int) -> None:
    seed_session(conn, HOLDER_A)
    _claim(
        conn,
        session_id=HOLDER_A,
        target_kind="item",
        scope_json=make_item_target(member).scope_json(),
    )


def test_approval_reaches_the_parked_claim_holder(test_db: Any) -> None:
    _project(test_db)
    _human_actor(test_db, REVIEWER)
    member = 9780
    request_id = _awaiting_review(
        test_db, run_id="run-verdict-approve", member=member, slug="verdict-approve"
    )
    _hold_the_item(test_db, member)

    resolve_decision_request(
        test_db,
        request_id,
        actor_id=REVIEWER,
        action="approve",
        note="The deployed stage matches the acceptance criteria.",
    )

    requirement_id = int(
        test_db.execute(
            "SELECT subject_key FROM decision_requests WHERE id=%s", (request_id,)
        ).fetchone()["subject_key"]
    )
    key = verdict_idempotency_key(requirement_id, "approve")
    assert _recipients(test_db, key) == [HOLDER_A]
    body = _bodies(test_db, key)[0]
    assert "was approved" in body
    assert "run-verdict-approve" in body
    assert "item-qa" in body
    assert "The deployed stage matches the acceptance criteria." in body
    # The verdict did what it says: the stage is accepted now.
    assert deployment_qa_stage_status(
        test_db,
        run_id="run-verdict-approve",
        stage_name="item-qa",
        member_item_id=member,
    )["accepted"]


def test_rejection_reaches_the_holder_with_its_next_step(test_db: Any) -> None:
    _project(test_db)
    _human_actor(test_db, REVIEWER)
    member = 9781
    request_id = _awaiting_review(
        test_db, run_id="run-verdict-reject", member=member, slug="verdict-reject"
    )
    _hold_the_item(test_db, member)

    resolve_decision_request(
        test_db,
        request_id,
        actor_id=REVIEWER,
        action="reject",
        note="The release banner still shows the previous version.",
    )

    requirement_id = int(
        test_db.execute(
            "SELECT subject_key FROM decision_requests WHERE id=%s", (request_id,)
        ).fetchone()["subject_key"]
    )
    key = verdict_idempotency_key(requirement_id, "reject")
    assert _recipients(test_db, key) == [HOLDER_A]
    body = _bodies(test_db, key)[0]
    assert "was rejected" in body
    assert "record fresh evidence" in body
    assert "The release banner still shows the previous version." in body
    # And the stage genuinely did not advance.
    assert not deployment_qa_stage_status(
        test_db,
        run_id="run-verdict-reject",
        stage_name="item-qa",
        member_item_id=member,
    )["accepted"]


def test_a_non_deployment_review_notifies_nobody(test_db: Any) -> None:
    """The module answers only for deployment-stage subjects."""
    from yoke_core.domain.deployment_qa_verdict_notice import (
        notify_deployment_qa_verdict,
    )

    _project(test_db)
    item_id = 9782
    insert_item(test_db, id=item_id, project_sequence=item_id, workflow_id="issue")
    now = "2026-09-14T00:00:00Z"
    requirement_id = int(
        test_db.execute(
            "INSERT INTO qa_requirements(item_id,qa_kind,qa_phase,blocking_mode,"
            "requirement_source,instructions,created_at) VALUES "
            "(%s,'release_qa','post_deploy','blocking','explicit','check it',%s) "
            "RETURNING id",
            (item_id, now),
        ).fetchone()["id"]
    )
    test_db.commit()

    assert (
        notify_deployment_qa_verdict(
            test_db, requirement_id=requirement_id, action="approve"
        )
        == ""
    )
