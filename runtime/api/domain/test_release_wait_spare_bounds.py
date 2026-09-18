"""The spare that keeps a release-wait owner alive is bounded and scoped.

An unbounded spare replaces one failure with a quieter one. A holder whose
machine never comes back would pin its item open forever, and nothing would
chase it: the stale-alive probe skips parked sessions by design, which is
exactly the population the spare protects. And sparing a session spares
every claim on it, so a holder carrying unrelated work would pin that open
too.

So each condition gets its own case, and each one that fails ends in the
sweep proceeding — which is what routes the item to steering rather than
leaving it unowned and unmentioned.
"""

from __future__ import annotations

import json
from typing import Any

from runtime.api.domain.coordination_claim_test_support import (
    PROJECT_YOKE,
    seed_project,
)
from runtime.api.domain.test_deployment_qa_stage_wake_delivery import (
    HOLDER_A,
    _claim,
    seed_session,
)
from runtime.api.fixtures.backlog_inserts import insert_item
from runtime.api.sessions_api_stale_test_helpers import _ago_minutes
from yoke_core.domain import release_wait_ownership as ownership
from yoke_core.domain import release_wait_sweep as sweep
from yoke_core.domain.actor_permissions import (
    ROLE_OWNER,
    grant_actor_project_role,
    seed_roles_and_permissions,
)
from yoke_core.domain.session_mode import SESSION_MODE_PARKED, set_session_mode
from yoke_core.domain.session_native_process_observation import (
    NATIVE_EXIT_CODE_KEY,
    NATIVE_PROCESS_GONE_AT_COLUMN,
    NATIVE_PROCESS_GONE_EVIDENCE_COLUMN,
)
from yoke_core.domain.session_reclaim_activity import (
    ReclaimClassification,
    read_activity_signals,
)
from yoke_core.domain.sessions_analytics_core import (
    DEFAULT_STALE_WITH_HOLDINGS_THRESHOLD_MINUTES,
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


def _parked_owner(conn: Any, item_id: int) -> None:
    insert_item(
        conn, id=item_id, project_sequence=item_id, workflow_id="dash", status="idea"
    )
    stage = delivery_redirect_stage(load_item_workflow_runtime(conn, item_id))
    assert stage, "the dash pin must declare a release wait"
    conn.execute("UPDATE items SET status=%s WHERE id=%s", (stage, item_id))
    seed_session(conn, HOLDER_A)
    _claim(
        conn,
        session_id=HOLDER_A,
        target_kind="item",
        scope_json=make_item_target(item_id).scope_json(),
    )
    set_session_mode(
        conn, HOLDER_A, SESSION_MODE_PARKED, ownership.park_reason("ITEM")
    )
    conn.commit()


def _stale(conn: Any) -> ReclaimClassification:
    return ReclaimClassification(
        is_reclaimable=True,
        reason="heartbeat_stale",
        evidence=read_activity_signals(conn, HOLDER_A),
    )


def _spared(conn: Any) -> bool:
    guarded = sweep.guard_release_wait_owner(conn, HOLDER_A, _stale(conn))
    return not guarded.is_reclaimable


def _quiet_for(conn: Any, minutes: int) -> None:
    stamp = _ago_minutes(minutes)
    conn.execute(
        "UPDATE harness_sessions SET last_heartbeat=%s, last_tool_call_at=%s, "
        "tool_call_count=1, episode_started_at=%s WHERE session_id=%s",
        (stamp, stamp, stamp, HOLDER_A),
    )
    conn.execute(
        "UPDATE work_claims SET last_heartbeat=%s, claimed_at=%s "
        "WHERE session_id=%s",
        (stamp, stamp, HOLDER_A),
    )
    conn.commit()


def _report_process_gone(conn: Any, *, exit_code: int) -> None:
    conn.execute(
        f"UPDATE harness_sessions SET {NATIVE_PROCESS_GONE_AT_COLUMN}=%s, "
        f"{NATIVE_PROCESS_GONE_EVIDENCE_COLUMN}=%s WHERE session_id=%s",
        (_ago_minutes(5), json.dumps({NATIVE_EXIT_CODE_KEY: exit_code}), HOLDER_A),
    )
    conn.commit()


def test_a_declared_owner_inside_the_bound_is_spared(test_db: Any) -> None:
    _project(test_db)
    _parked_owner(test_db, 9831)
    _quiet_for(test_db, DEFAULT_STALE_WITH_HOLDINGS_THRESHOLD_MINUTES + 60)

    assert _spared(test_db) is True


def test_quiet_past_the_retention_bound_is_no_longer_spared(test_db: Any) -> None:
    """Silence past the multiple of the holdings TTL ends the spare, and the
    sweep hands the item to steering instead. The case derives its own gap
    from the same two constants rather than naming a duration, because the
    TTL is a machine-owned setting and any fixed number here would pass or
    fail by which box ran it."""
    _project(test_db)
    _parked_owner(test_db, 9832)
    _quiet_for(
        test_db,
        DEFAULT_STALE_WITH_HOLDINGS_THRESHOLD_MINUTES
        * (sweep.RELEASE_WAIT_TTL_MULTIPLIER + 1),
    )

    assert _spared(test_db) is False


def test_an_unaccounted_process_death_ends_the_spare(test_db: Any) -> None:
    """A non-zero exit is the death the product still calls a disappearance,
    so the owner cannot be resumed and the item needs restaffing."""
    _project(test_db)
    _parked_owner(test_db, 9833)
    _quiet_for(test_db, DEFAULT_STALE_WITH_HOLDINGS_THRESHOLD_MINUTES + 60)
    _report_process_gone(test_db, exit_code=3)

    assert _spared(test_db) is False


def test_a_clean_exit_under_the_park_is_the_wait_not_a_death(test_db: Any) -> None:
    """A headless command ending its turn parked is the ordinary shape; the
    relay resumes it on the next wake, so it stays spared."""
    _project(test_db)
    _parked_owner(test_db, 9834)
    _quiet_for(test_db, DEFAULT_STALE_WITH_HOLDINGS_THRESHOLD_MINUTES + 60)
    _report_process_gone(test_db, exit_code=0)

    assert _spared(test_db) is True


def test_a_holder_carrying_other_claims_is_not_spared(test_db: Any) -> None:
    """Sparing a session spares everything it holds, so an owner carrying
    unrelated work is swept; the item still reaches steering."""
    _project(test_db)
    _parked_owner(test_db, 9835)
    _claim(
        test_db,
        session_id=HOLDER_A,
        target_kind="steering",
        scope_json=make_steering_target(PROJECT_YOKE).scope_json(),
    )
    _quiet_for(test_db, DEFAULT_STALE_WITH_HOLDINGS_THRESHOLD_MINUTES + 60)

    assert _spared(test_db) is False


def test_a_second_release_wait_does_not_count_as_other_work(test_db: Any) -> None:
    _project(test_db)
    _parked_owner(test_db, 9836)
    insert_item(
        test_db, id=9837, project_sequence=9837, workflow_id="dash", status="idea"
    )
    stage = delivery_redirect_stage(load_item_workflow_runtime(test_db, 9837))
    test_db.execute("UPDATE items SET status=%s WHERE id=%s", (stage, 9837))
    _claim(
        test_db,
        session_id=HOLDER_A,
        target_kind="item",
        scope_json=make_item_target(9837).scope_json(),
    )
    _quiet_for(test_db, DEFAULT_STALE_WITH_HOLDINGS_THRESHOLD_MINUTES + 60)

    assert _spared(test_db) is True
