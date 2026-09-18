"""An item at its release wait keeps an owner until it reaches done.

The retention these cover was previously undone by three separate paths, so
each one is exercised where it actually decides: the sweep that reclaims a
quiet session, the hand-off that answers for an abandoned wait, and the
merge close-out that parks the session in the first place.

The dash pin's release wait is ``release``; these read it from the same
``delivery_redirect_stage`` the product does rather than restating it, so a
definition change moves the tests with it.
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
from yoke_core.domain import release_wait_ownership as ownership
from yoke_core.domain.actor_permissions import (
    ROLE_OWNER,
    grant_actor_project_role,
    seed_roles_and_permissions,
)
from yoke_core.domain.session_mode import SESSION_MODE_PARKED, set_session_mode
from yoke_core.domain.session_reclaim_activity import (
    ReclaimClassification,
    read_activity_signals,
)
from yoke_core.domain.work_claim_targets import make_item_target, make_steering_target
from yoke_core.domain.workflow_behavior import delivery_redirect_stage
from yoke_core.domain.workflow_runtime import load_item_workflow_runtime


def _project(conn: Any) -> None:
    seed_project(conn, PROJECT_YOKE, "yoke")
    seed_roles_and_permissions(conn)
    grant_actor_project_role(
        conn, actor_id=2, project_id=PROJECT_YOKE, role_name=ROLE_OWNER
    )


def _release_stage(conn: Any, item_id: int) -> str:
    stage = delivery_redirect_stage(load_item_workflow_runtime(conn, item_id))
    assert stage, "the dash pin must declare a release wait"
    return stage


def _dash_item(conn: Any, item_id: int, *, status: str = "") -> str:
    insert_item(
        conn, id=item_id, project_sequence=item_id, workflow_id="dash", status="idea"
    )
    stage = _release_stage(conn, item_id)
    conn.execute(
        "UPDATE items SET status=%s WHERE id=%s", (status or stage, item_id)
    )
    conn.commit()
    return stage


def _held(conn: Any, item_id: int) -> list[str]:
    rows = conn.execute(
        "SELECT session_id FROM work_claims WHERE released_at IS NULL "
        "AND target_kind='item' AND scope=%s",
        (make_item_target(item_id).scope_json(),),
    ).fetchall()
    return [row["session_id"] for row in rows]


def _own_item(conn: Any, session_id: str, item_id: int) -> None:
    seed_session(conn, session_id)
    _claim(
        conn,
        session_id=session_id,
        target_kind="item",
        scope_json=make_item_target(item_id).scope_json(),
    )


def _classified(conn: Any, *, reclaimable: bool) -> ReclaimClassification:
    """A real classification for HOLDER_A, with the verdict this case needs."""
    return ReclaimClassification(
        is_reclaimable=reclaimable,
        reason="heartbeat_stale" if reclaimable else "fresh",
        evidence=read_activity_signals(conn, HOLDER_A),
    )


def test_a_parked_owner_of_a_release_wait_is_named_as_one(test_db: Any) -> None:
    _project(test_db)
    stage = _dash_item(test_db, 9801)
    _own_item(test_db, HOLDER_A, 9801)

    [owned] = ownership.owned_release_waits(test_db, HOLDER_A)

    assert owned["item_id"] == 9801
    assert owned["status"] == stage
    assert owned["public_ref"].endswith("-9801")


def test_an_item_short_of_its_release_wait_is_not_one(test_db: Any) -> None:
    _project(test_db)
    _dash_item(test_db, 9802, status="reviewing-implementation")
    _own_item(test_db, HOLDER_A, 9802)

    assert ownership.owned_release_waits(test_db, HOLDER_A) == []


def test_an_item_that_reached_done_is_no_longer_a_release_wait(test_db: Any) -> None:
    """The claim releases at done and not before: once the item is terminal
    the owner is an ordinary reclaim candidate again."""
    _project(test_db)
    _dash_item(test_db, 9803, status="done")
    _own_item(test_db, HOLDER_A, 9803)
    set_session_mode(test_db, HOLDER_A, SESSION_MODE_PARKED, "awaiting delivery")

    assert ownership.owned_release_waits(test_db, HOLDER_A) == []
    assert ownership.guard_release_wait_owner(
        test_db, HOLDER_A, _classified(test_db, reclaimable=True)
    ).is_reclaimable


def test_the_sweep_spares_a_parked_release_wait_owner(test_db: Any) -> None:
    _project(test_db)
    _dash_item(test_db, 9804)
    _own_item(test_db, HOLDER_A, 9804)
    set_session_mode(
        test_db, HOLDER_A, SESSION_MODE_PARKED, ownership.park_reason("YOK-9804")
    )

    guarded = ownership.guard_release_wait_owner(
        test_db, HOLDER_A, _classified(test_db, reclaimable=True)
    )

    assert guarded.is_reclaimable is False
    assert guarded.reason == ownership.REASON_RELEASE_WAIT_OWNER


def test_an_undeclared_release_wait_owner_is_still_reclaimable(test_db: Any) -> None:
    """A holder that never parked declared no wait, so it is gone as far as
    the control plane can tell and the sweep proceeds."""
    _project(test_db)
    _dash_item(test_db, 9805)
    _own_item(test_db, HOLDER_A, 9805)

    assert ownership.guard_release_wait_owner(
        test_db, HOLDER_A, _classified(test_db, reclaimable=True)
    ).is_reclaimable


def test_a_fresh_session_is_never_re_decided_by_the_guard(test_db: Any) -> None:
    _project(test_db)
    _dash_item(test_db, 9806)
    _own_item(test_db, HOLDER_A, 9806)
    set_session_mode(test_db, HOLDER_A, SESSION_MODE_PARKED, "awaiting delivery")
    fresh = _classified(test_db, reclaimable=False)

    assert ownership.guard_release_wait_owner(test_db, HOLDER_A, fresh) is fresh


def test_an_orphaned_release_wait_is_handed_to_steering_by_name(
    test_db: Any,
) -> None:
    _project(test_db)
    _dash_item(test_db, 9807)
    _own_item(test_db, HOLDER_A, 9807)
    owed = ownership.owned_release_waits(test_db, HOLDER_A)
    # The sweep sends after the release, so the notice resolves the seat
    # rather than the session it just decided was gone.
    test_db.execute(
        "UPDATE work_claims SET released_at=%s, release_reason='reclaimed' "
        "WHERE session_id=%s",
        ("2026-09-18T00:00:00Z", HOLDER_A),
    )
    seed_session(test_db, HOLDER_B)
    _claim(
        test_db,
        session_id=HOLDER_B,
        target_kind="steering",
        scope_json=make_steering_target(PROJECT_YOKE).scope_json(),
    )

    [report] = ownership.hand_off_release_wait(test_db, HOLDER_A, owed)

    assert report["delivery"] in ("delivered", "undelivered")
    key = ownership.handoff_idempotency_key(9807, HOLDER_A)
    assert _recipients(test_db, key) == [HOLDER_B]
    [body] = _bodies(test_db, key)
    assert report["public_ref"] in body
    assert HOLDER_A in body
    assert "This seat is the addressable owner" in body


def test_nothing_owed_sends_nothing(test_db: Any) -> None:
    _project(test_db)

    assert ownership.hand_off_release_wait(test_db, HOLDER_A, []) == []
