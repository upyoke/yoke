"""A member whose own item-scoped QA is accepted is woken while the run runs.

The release-to-done gate already answers for one item. These cover the wake
that was missing: the parked owner is told as soon as that gate is empty,
independent of run status and of every other member, and a run-scoped stage
the flow declares still blocks the send.
"""

from __future__ import annotations

from typing import Any

from runtime.api.domain.test_deployment_delivery_close_out_notice import (
    _member_at_release_wait,
    _parked_owner,
)
from runtime.api.domain.test_deployment_qa_run_acceptance import _settle
from runtime.api.domain.test_deployment_qa_stage_execution import (
    _plan,
    _seed_run,
    _stages,
)
from runtime.api.domain.test_deployment_qa_stage_ordering import (
    _stages as _run_scoped_stages,
)
from runtime.api.domain.test_deployment_qa_stage_wake_delivery import (
    HOLDER_A,
    HOLDER_B,
    _bodies,
    _project,
    _recipients,
)
from yoke_core.domain import deployment_qa_member_acceptance_notice as notice
from yoke_core.domain.deployment_qa_member_acceptance_notice import (
    item_qa_accepted_idempotency_key,
)
from yoke_core.domain.deployment_qa_run_acceptance import (
    item_qa_acceptance_blockers,
)
from yoke_core.domain.deployment_qa_stage_gate import deployment_qa_stage_status


MEMBER_A = 33261
MEMBER_B = 33262
MEMBER_SHARED = 33263
MEMBER_DONE = 33264


def _executing_run(
    conn: Any,
    run_id: str,
    members: tuple[int, ...],
    *,
    stages: list | None = None,
    plan_slug: str,
) -> None:
    _project(conn)
    for item_id in members:
        _member_at_release_wait(conn, item_id)
        _parked_owner(conn, HOLDER_A if item_id == members[0] else HOLDER_B, item_id)
    _seed_run(
        conn,
        run_id=run_id,
        stages=stages or _stages(_plan(conn, plan_slug)),
        members=(),
        existing_members=members,
    )


def test_accepted_item_qa_wakes_the_parked_owner_while_the_run_executes(
    test_db: Any,
) -> None:
    _executing_run(test_db, "run-item-qa-wake", (MEMBER_A,), plan_slug="wake-holder")
    _settle(test_db, run_id="run-item-qa-wake", stage="item-qa", member=MEMBER_A)

    assert (
        item_qa_acceptance_blockers(
            test_db, run_id="run-item-qa-wake", item_id=MEMBER_A
        )
        == []
    )
    assert (
        test_db.execute(
            "SELECT status FROM deployment_runs WHERE id='run-item-qa-wake'"
        ).fetchone()["status"]
        == "executing"
    )
    key = item_qa_accepted_idempotency_key(MEMBER_A, "run-item-qa-wake")
    assert _recipients(test_db, key) == [HOLDER_A]
    [body] = _bodies(test_db, key)
    assert "item-scoped QA gate is clear" in body
    assert "still be executing" in body
    assert "will auto-close" in body
    assert "do not re-run merge solely" in body
    assert "yoke sessions touch --mode parked" in body
    assert "You hold its work claim" in body


def test_a_second_settle_of_the_same_acceptance_sends_nothing_more(
    test_db: Any,
) -> None:
    _executing_run(test_db, "run-item-qa-once", (MEMBER_A,), plan_slug="wake-once")
    _settle(test_db, run_id="run-item-qa-once", stage="item-qa", member=MEMBER_A)
    again = deployment_qa_stage_status(
        test_db,
        run_id="run-item-qa-once",
        stage_name="item-qa",
        member_item_id=MEMBER_A,
    )
    assert again["accepted"] is True
    key = item_qa_accepted_idempotency_key(MEMBER_A, "run-item-qa-once")
    assert len(_bodies(test_db, key)) == 1


def test_a_sibling_with_outstanding_item_qa_is_not_woken(test_db: Any) -> None:
    _executing_run(
        test_db, "run-item-qa-sib", (MEMBER_A, MEMBER_B), plan_slug="wake-sib"
    )
    _settle(test_db, run_id="run-item-qa-sib", stage="item-qa", member=MEMBER_A)

    assert _recipients(
        test_db, item_qa_accepted_idempotency_key(MEMBER_A, "run-item-qa-sib")
    ) == [HOLDER_A]
    assert (
        _recipients(
            test_db, item_qa_accepted_idempotency_key(MEMBER_B, "run-item-qa-sib")
        )
        == []
    )
    assert item_qa_acceptance_blockers(
        test_db, run_id="run-item-qa-sib", item_id=MEMBER_B
    )


def test_a_run_scoped_stage_still_blocks_the_member_wake(test_db: Any) -> None:
    _executing_run(
        test_db,
        "run-item-qa-shared",
        (MEMBER_SHARED,),
        stages=_run_scoped_stages(_plan(test_db, "wake-shared")),
        plan_slug="wake-shared",
    )
    for stage in ("member-qa-one", "member-qa-two"):
        test_db.execute(
            "UPDATE deployment_runs SET current_stage=%s WHERE id=%s",
            (stage, "run-item-qa-shared"),
        )
        test_db.commit()
        _settle(test_db, run_id="run-item-qa-shared", stage=stage, member=MEMBER_SHARED)

    blockers = item_qa_acceptance_blockers(
        test_db, run_id="run-item-qa-shared", item_id=MEMBER_SHARED
    )
    assert any("release-qa" in reason for reason in blockers)
    assert (
        _recipients(
            test_db,
            item_qa_accepted_idempotency_key(MEMBER_SHARED, "run-item-qa-shared"),
        )
        == []
    )


def test_a_member_not_at_its_release_wait_is_not_told(test_db: Any) -> None:
    _project(test_db)
    _seed_run(
        test_db,
        run_id="run-item-qa-done",
        stages=_stages(_plan(test_db, "wake-done")),
        members=(MEMBER_DONE,),
    )
    _settle(test_db, run_id="run-item-qa-done", stage="item-qa", member=MEMBER_DONE)
    assert (
        _recipients(
            test_db, item_qa_accepted_idempotency_key(MEMBER_DONE, "run-item-qa-done")
        )
        == []
    )


def test_a_failed_send_does_not_undo_the_recorded_acceptance(
    test_db: Any, monkeypatch
) -> None:
    _executing_run(test_db, "run-item-qa-fail", (MEMBER_A,), plan_slug="wake-fail")
    real = notice.push_member_notice

    def boom(*args, **kwargs):
        test_db.execute("SELECT * FROM a_relation_that_does_not_exist")
        return real(*args, **kwargs)

    monkeypatch.setattr(notice, "push_member_notice", boom)
    _settle(test_db, run_id="run-item-qa-fail", stage="item-qa", member=MEMBER_A)
    assert (
        deployment_qa_stage_status(
            test_db,
            run_id="run-item-qa-fail",
            stage_name="item-qa",
            member_item_id=MEMBER_A,
        )["accepted"]
        is True
    )
    assert (
        item_qa_acceptance_blockers(
            test_db, run_id="run-item-qa-fail", item_id=MEMBER_A
        )
        == []
    )
    assert (
        _recipients(
            test_db, item_qa_accepted_idempotency_key(MEMBER_A, "run-item-qa-fail")
        )
        == []
    )
