"""A succeeded run wakes the parked owner whose own wait it actually cleared.

Two failure modes shape these, and both come from the notice being wrong
rather than absent. Announcing a clearance that did not happen unparks an
owner who still has to wait, which is the abandonment the retention exists
to prevent; and a send that aborts its caller's transaction on Postgres
takes the run's own 'succeeded' write with it. So the discharge test and the
isolation are exercised against a real database, not around them.
"""

from __future__ import annotations

from typing import Any

from runtime.api.domain.coordination_claim_test_support import (
    PROJECT_YOKE,
    seed_project,
)
from runtime.api.domain.test_deployment_qa_stage_wake_delivery import (
    HOLDER_A,
    HOLDER_B,
    _bodies,
    _claim,
    _recipients,
    seed_session,
)
from runtime.api.fixtures.backlog_inserts import insert_item
from yoke_core.domain import deployment_delivery_close_out_notice as notice
from yoke_core.domain.actor_permissions import (
    ROLE_OWNER,
    grant_actor_project_role,
    seed_roles_and_permissions,
)
from yoke_core.domain.db_helpers import iso8601_now
from yoke_core.domain.deployment_delivery_close_out_notice import (
    delivery_cleared_idempotency_key,
    notify_delivery_cleared,
)
from yoke_core.domain.session_mode import SESSION_MODE_PARKED, set_session_mode
from yoke_core.domain.work_claim_targets import make_item_target, make_steering_target
from yoke_core.domain.workflow_behavior import delivery_redirect_stage
from yoke_core.domain.workflow_runtime import load_item_workflow_runtime

#: The flow that may close these items, and the one that may not.
COMPLETION_FLOW = "prod-flow"
SIBLING_FLOW = "stage-flow"


def _project(conn: Any) -> None:
    seed_project(conn, PROJECT_YOKE, "yoke")
    seed_roles_and_permissions(conn)
    grant_actor_project_role(
        conn, actor_id=2, project_id=PROJECT_YOKE, role_name=ROLE_OWNER
    )


def _run(conn: Any, run_id: str, *, flow: str, members: tuple[int, ...]) -> None:
    now = iso8601_now()
    conn.execute(
        "INSERT INTO deployment_runs (id,project_id,flow,status,created_at) "
        "VALUES (%s,%s,%s,'succeeded',%s) ON CONFLICT(id) DO NOTHING",
        (run_id, PROJECT_YOKE, flow, now),
    )
    for item_id in members:
        conn.execute(
            "INSERT INTO deployment_run_items (run_id,item_id,added_at) "
            "VALUES (%s,%s,%s)",
            (run_id, item_id, now),
        )
    conn.commit()


def _member_at_release_wait(conn: Any, item_id: int, *, status: str = "") -> None:
    insert_item(
        conn,
        id=item_id,
        project_sequence=item_id,
        workflow_id="dash",
        status="idea",
        deployment_flow=COMPLETION_FLOW,
    )
    stage = delivery_redirect_stage(load_item_workflow_runtime(conn, item_id))
    assert stage, "the dash pin must declare a release wait"
    conn.execute(
        "UPDATE items SET status=%s WHERE id=%s", (status or stage, item_id)
    )
    conn.commit()


def _parked_owner(conn: Any, session_id: str, item_id: int) -> None:
    seed_session(conn, session_id)
    _claim(
        conn,
        session_id=session_id,
        target_kind="item",
        scope_json=make_item_target(item_id).scope_json(),
    )
    set_session_mode(conn, session_id, SESSION_MODE_PARKED, "awaiting delivery")


def test_the_parked_holder_is_told_its_wait_is_over(test_db: Any) -> None:
    _project(test_db)
    _member_at_release_wait(test_db, 9811)
    _run(test_db, "run-cleared", flow=COMPLETION_FLOW, members=(9811,))
    _parked_owner(test_db, HOLDER_A, 9811)

    [report] = notify_delivery_cleared(test_db, run_id="run-cleared")

    assert report["delivery"] in ("delivered", "undelivered")
    key = delivery_cleared_idempotency_key(9811, "run-cleared")
    assert _recipients(test_db, key) == [HOLDER_A]
    [body] = _bodies(test_db, key)
    assert "run-cleared" in body
    assert "You hold its work claim" in body
    assert "yoke merge item" in body
    assert "re-park before going quiet" in body


def test_a_sibling_flow_run_tells_the_holder_nothing(test_db: Any) -> None:
    """The stage half of a stage-then-production pair does not discharge the
    item's release obligation, and saying otherwise would unpark an owner
    whose close-out is still going to be refused."""
    _project(test_db)
    _member_at_release_wait(test_db, 9814)
    _run(test_db, "run-stage", flow=SIBLING_FLOW, members=(9814,))
    _parked_owner(test_db, HOLDER_A, 9814)

    assert notify_delivery_cleared(test_db, run_id="run-stage") == []
    assert _recipients(
        test_db, delivery_cleared_idempotency_key(9814, "run-stage")
    ) == []


def test_the_completion_flow_run_of_the_same_pair_does_tell_it(test_db: Any) -> None:
    _project(test_db)
    _member_at_release_wait(test_db, 9815)
    _run(test_db, "run-stage-2", flow=SIBLING_FLOW, members=(9815,))
    _parked_owner(test_db, HOLDER_A, 9815)
    assert notify_delivery_cleared(test_db, run_id="run-stage-2") == []

    _run(test_db, "run-prod", flow=COMPLETION_FLOW, members=(9815,))

    [report] = notify_delivery_cleared(test_db, run_id="run-prod")
    assert report["public_ref"].endswith("-9815")
    assert _recipients(
        test_db, delivery_cleared_idempotency_key(9815, "run-prod")
    ) == [HOLDER_A]


def test_an_unowned_wait_reaches_the_steering_seat_instead(test_db: Any) -> None:
    _project(test_db)
    _member_at_release_wait(test_db, 9812)
    _run(test_db, "run-unowned", flow=COMPLETION_FLOW, members=(9812,))
    seed_session(test_db, HOLDER_B)
    _claim(
        test_db,
        session_id=HOLDER_B,
        target_kind="steering",
        scope_json=make_steering_target(PROJECT_YOKE).scope_json(),
    )

    [report] = notify_delivery_cleared(test_db, run_id="run-unowned")

    assert report["delivery"] in ("delivered", "undelivered")
    key = delivery_cleared_idempotency_key(9812, "run-unowned")
    assert _recipients(test_db, key) == [HOLDER_B]
    [body] = _bodies(test_db, key)
    assert "Nobody holds its work claim" in body
    assert "/yoke dash" in body


def test_a_member_past_its_release_wait_is_not_told_again(test_db: Any) -> None:
    """A run carries members at every stage; only one still waiting is owed
    a close-out, and an item already done is not."""
    _project(test_db)
    _member_at_release_wait(test_db, 9813, status="done")
    _run(test_db, "run-done-member", flow=COMPLETION_FLOW, members=(9813,))
    _parked_owner(test_db, HOLDER_A, 9813)

    assert notify_delivery_cleared(test_db, run_id="run-done-member") == []
    assert (
        _recipients(test_db, delivery_cleared_idempotency_key(9813, "run-done-member"))
        == []
    )


def test_one_failed_send_neither_aborts_the_caller_nor_its_siblings(
    test_db: Any, monkeypatch
) -> None:
    """On Postgres a failed statement poisons the whole transaction, so an
    unisolated send would take its siblings — and, before the reorder, the
    run's own 'succeeded' write — down with it."""
    _project(test_db)
    for item_id in (9816, 9817):
        _member_at_release_wait(test_db, item_id)
    _run(test_db, "run-partial", flow=COMPLETION_FLOW, members=(9816, 9817))
    _parked_owner(test_db, HOLDER_A, 9816)
    _parked_owner(test_db, HOLDER_B, 9817)
    real = notice.push_notice

    def flaky(conn, *, item_id, **kwargs):
        if int(item_id) == 9816:
            conn.execute("SELECT * FROM a_relation_that_does_not_exist")
        return real(conn, item_id=item_id, **kwargs)

    monkeypatch.setattr(notice, "push_notice", flaky)

    reports = {r["public_ref"][-4:]: r["delivery"] for r in notify_delivery_cleared(
        test_db, run_id="run-partial"
    )}

    assert reports["9816"].startswith("failed: ")
    assert reports["9817"] in ("delivered", "undelivered")
    # The connection survived, and the sibling's row is really there.
    assert _recipients(
        test_db, delivery_cleared_idempotency_key(9817, "run-partial")
    ) == [HOLDER_B]
    assert _recipients(
        test_db, delivery_cleared_idempotency_key(9816, "run-partial")
    ) == []
    assert test_db.execute(
        "SELECT status FROM deployment_runs WHERE id='run-partial'"
    ).fetchone()["status"] == "succeeded"
