"""A succeeded run wakes the parked owner whose release wait it cleared.

The owner of a release wait parks and goes quiet on purpose, so a delivery
that told it nothing left the item held by a session with no reason to act.
These run the real recipient resolution and message insert against a real
database, because a wiring defect in that lookup is exactly the failure the
notice exists to prevent.
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

RUN_ID = "run-delivery-cleared"


def _project(conn: Any) -> None:
    seed_project(conn, PROJECT_YOKE, "yoke")
    seed_roles_and_permissions(conn)
    grant_actor_project_role(
        conn, actor_id=2, project_id=PROJECT_YOKE, role_name=ROLE_OWNER
    )


def _member(conn: Any, item_id: int, *, run_id: str, status: str = "") -> str:
    insert_item(
        conn, id=item_id, project_sequence=item_id, workflow_id="dash", status="idea"
    )
    stage = delivery_redirect_stage(load_item_workflow_runtime(conn, item_id))
    assert stage, "the dash pin must declare a release wait"
    conn.execute(
        "UPDATE items SET status=%s WHERE id=%s", (status or stage, item_id)
    )
    now = iso8601_now()
    conn.execute(
        "INSERT INTO deployment_runs (id,project_id,flow,status,created_at) "
        "VALUES (%s,%s,'prod-default','succeeded',%s) "
        "ON CONFLICT(id) DO NOTHING",
        (run_id, PROJECT_YOKE, now),
    )
    conn.execute(
        "INSERT INTO deployment_run_items (run_id,item_id,added_at) "
        "VALUES (%s,%s,%s)",
        (run_id, item_id, now),
    )
    conn.commit()
    return stage


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
    _member(test_db, 9811, run_id=RUN_ID)
    _parked_owner(test_db, HOLDER_A, 9811)

    [report] = notify_delivery_cleared(test_db, run_id=RUN_ID)

    assert report["delivery"] in ("delivered", "undelivered")
    key = delivery_cleared_idempotency_key(9811, RUN_ID)
    assert _recipients(test_db, key) == [HOLDER_A]
    [body] = _bodies(test_db, key)
    assert RUN_ID in body
    assert "You hold its work claim" in body
    assert "yoke merge item" in body


def test_an_unowned_wait_reaches_the_steering_seat_instead(test_db: Any) -> None:
    _project(test_db)
    _member(test_db, 9812, run_id="run-unowned")
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
    _member(test_db, 9813, run_id="run-done-member", status="done")
    _parked_owner(test_db, HOLDER_A, 9813)

    assert notify_delivery_cleared(test_db, run_id="run-done-member") == []
    assert (
        _recipients(test_db, delivery_cleared_idempotency_key(9813, "run-done-member"))
        == []
    )
