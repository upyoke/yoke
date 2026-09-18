"""The stale sweep is where a release wait lost its owner; here it keeps one.

Driven through the real ``clean_stale_harness_sessions`` rather than the
guard in isolation, because the defect was the sweep releasing a claim the
merge close-out had deliberately retained. A declared wait survives the sweep
outright; an undeclared one is still reclaimed, and the item it orphaned is
named to the project's steering seat instead of dropped.

Every holder here is staled past the holdings-aware TTL, not the base one: a
claim-holding session gets the long threshold, so a shorter gap would prove
nothing about which sessions this sweep spares.
"""

from __future__ import annotations

from typing import Any

from runtime.api.domain.coordination_claim_test_support import (
    PROJECT_YOKE,
    seed_project,
)
from runtime.api.domain.test_deployment_qa_stage_wake_delivery import (
    HOLDER_B,
    _bodies,
    _claim,
    _recipients,
    seed_session,
)
from runtime.api.fixtures.backlog_inserts import insert_item
from runtime.api.sessions_api_stale_test_helpers import _ago_minutes
from yoke_core.domain import release_wait_ownership as ownership
from yoke_core.domain.actor_permissions import (
    ROLE_OWNER,
    grant_actor_project_role,
    seed_roles_and_permissions,
)
from yoke_core.domain.session_mode import SESSION_MODE_PARKED, set_session_mode
from yoke_core.domain.sessions import clean_stale_harness_sessions
from yoke_core.domain.work_claim_targets import make_item_target, make_steering_target
from yoke_core.domain.workflow_behavior import delivery_redirect_stage
from yoke_core.domain.workflow_runtime import load_item_workflow_runtime

OWNER = "release-wait-owner"

#: Past ``session_stale_ttl_with_holdings_minutes``, which defaults to a day.
STALE_MINUTES = 2000


def _project(conn: Any) -> None:
    seed_project(conn, PROJECT_YOKE, "yoke")
    seed_roles_and_permissions(conn)
    grant_actor_project_role(
        conn, actor_id=2, project_id=PROJECT_YOKE, role_name=ROLE_OWNER
    )


def _dash_item(conn: Any, item_id: int, *, at_release_wait: bool) -> None:
    insert_item(
        conn, id=item_id, project_sequence=item_id, workflow_id="dash", status="idea"
    )
    if not at_release_wait:
        return
    stage = delivery_redirect_stage(load_item_workflow_runtime(conn, item_id))
    assert stage, "the dash pin must declare a release wait"
    conn.execute("UPDATE items SET status=%s WHERE id=%s", (stage, item_id))
    conn.commit()


def _quiet_owner(conn: Any, item_id: int, *, parked: bool) -> None:
    seed_session(conn, OWNER)
    _claim(
        conn,
        session_id=OWNER,
        target_kind="item",
        scope_json=make_item_target(item_id).scope_json(),
    )
    if parked:
        set_session_mode(
            conn, OWNER, SESSION_MODE_PARKED, ownership.park_reason("ITEM")
        )
    stale_at = _ago_minutes(STALE_MINUTES)
    conn.execute(
        "UPDATE harness_sessions SET last_heartbeat=%s, last_tool_call_at=%s, "
        "tool_call_count=1, episode_started_at=%s WHERE session_id=%s",
        (stale_at, stale_at, stale_at, OWNER),
    )
    conn.execute(
        "UPDATE work_claims SET last_heartbeat=%s, claimed_at=%s "
        "WHERE session_id=%s",
        (stale_at, stale_at, OWNER),
    )
    conn.commit()


def _steering_seat(conn: Any) -> None:
    seed_session(conn, HOLDER_B)
    _claim(
        conn,
        session_id=HOLDER_B,
        target_kind="steering",
        scope_json=make_steering_target(PROJECT_YOKE).scope_json(),
    )


def _live_claim(conn: Any, item_id: int) -> list[str]:
    rows = conn.execute(
        "SELECT session_id FROM work_claims WHERE released_at IS NULL "
        "AND target_kind='item' AND scope=%s",
        (make_item_target(item_id).scope_json(),),
    ).fetchall()
    return [row["session_id"] for row in rows]


def test_a_parked_release_wait_owner_keeps_its_claim_through_the_sweep(
    test_db: Any,
) -> None:
    _project(test_db)
    _dash_item(test_db, 9821, at_release_wait=True)
    _quiet_owner(test_db, 9821, parked=True)

    result = clean_stale_harness_sessions(test_db, stale_threshold_minutes=10)

    assert result["total_reclaimed"] == 0
    assert _live_claim(test_db, 9821) == [OWNER]
    row = test_db.execute(
        "SELECT ended_at FROM harness_sessions WHERE session_id=%s", (OWNER,)
    ).fetchone()
    assert row["ended_at"] is None


def test_an_undeclared_owner_is_reclaimed_and_its_item_named_to_steering(
    test_db: Any,
) -> None:
    _project(test_db)
    _dash_item(test_db, 9822, at_release_wait=True)
    _quiet_owner(test_db, 9822, parked=False)
    _steering_seat(test_db)

    result = clean_stale_harness_sessions(test_db, stale_threshold_minutes=10)

    assert result["total_reclaimed"] == 1
    assert _live_claim(test_db, 9822) == []
    key = ownership.handoff_idempotency_key(9822, OWNER)
    assert _recipients(test_db, key) == [HOLDER_B]
    [body] = _bodies(test_db, key)
    assert "is at its release wait and its owner is gone" in body
    assert OWNER in body


def test_a_quiet_session_owning_no_release_wait_is_swept_as_before(
    test_db: Any,
) -> None:
    """The guard answers for release waits only; every other stale holder
    keeps the behaviour the sweep already had, park or no park."""
    _project(test_db)
    _dash_item(test_db, 9823, at_release_wait=False)
    _quiet_owner(test_db, 9823, parked=True)
    _steering_seat(test_db)

    result = clean_stale_harness_sessions(test_db, stale_threshold_minutes=10)

    assert result["total_reclaimed"] == 1
    assert _live_claim(test_db, 9823) == []
    assert _recipients(
        test_db, ownership.handoff_idempotency_key(9823, OWNER)
    ) == []
