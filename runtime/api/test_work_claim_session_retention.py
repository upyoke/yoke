"""Persisted work claims protect sessions throughout idle and startup sweeps."""

from __future__ import annotations

import json
from typing import Any

import pytest

from runtime.api.domain.coordination_claim_test_support import (
    PROJECT_YOKE,
    seed_project,
)
from runtime.api.domain.test_deployment_qa_stage_wake_delivery import (
    _claim,
    seed_session,
)
from runtime.api.fixtures.backlog_inserts import insert_item
from runtime.api.sessions_api_stale_test_helpers import _ago_minutes
from yoke_core.domain.session_mode import SESSION_MODE_PARKED, set_session_mode
from yoke_core.domain.sessions import clean_stale_harness_sessions
from yoke_core.domain.sessions_analytics import SessionError
from yoke_core.domain.sessions_render_end import end_session
from yoke_core.domain.sessions_render_reclaim import reclaim_stale_session
from yoke_core.domain.work_claim_targets import make_item_target
from yoke_core.domain.workflow_behavior import delivery_redirect_stage
from yoke_core.domain.workflow_runtime import load_item_workflow_runtime


@pytest.fixture
def held_session(test_db: Any):
    seed_project(test_db, PROJECT_YOKE, "yoke")
    seed_session(test_db, "owner")

    def hold(item_id: int, *, release_wait: bool = False, parked: bool = False) -> None:
        insert_item(
            test_db,
            id=item_id,
            project_sequence=item_id,
            workflow_id="dash",
            status="idea",
        )
        if release_wait:
            stage = delivery_redirect_stage(
                load_item_workflow_runtime(test_db, item_id)
            )
            assert stage
            test_db.execute("UPDATE items SET status=%s WHERE id=%s", (stage, item_id))
        _claim(
            test_db,
            session_id="owner",
            target_kind="item",
            scope_json=make_item_target(item_id).scope_json(),
        )
        if parked:
            set_session_mode(test_db, "owner", SESSION_MODE_PARKED, "awaiting delivery")
        old = _ago_minutes(20_000)
        test_db.execute(
            "UPDATE harness_sessions SET last_heartbeat=%s, last_tool_call_at=%s, "
            "tool_call_count=1, episode_started_at=%s WHERE session_id='owner'",
            (old, old, old),
        )
        test_db.execute(
            "UPDATE work_claims SET claimed_at=%s, last_heartbeat=%s "
            "WHERE session_id='owner'",
            (old, old),
        )
        test_db.commit()

    return test_db, hold


def _still_held(conn: Any) -> None:
    session = conn.execute(
        "SELECT ended_at FROM harness_sessions WHERE session_id='owner'"
    ).fetchone()
    claim = conn.execute(
        "SELECT released_at FROM work_claims WHERE session_id='owner'"
    ).fetchone()
    assert session["ended_at"] is None
    assert claim["released_at"] is None


@pytest.mark.parametrize(
    "release_wait,parked", [(False, False), (True, False), (True, True)]
)
def test_idle_sweep_keeps_every_work_claim_holder(held_session, release_wait, parked):
    conn, hold = held_session
    hold(9871, release_wait=release_wait, parked=parked)

    result = clean_stale_harness_sessions(conn, stale_threshold_minutes=10)

    assert result["total_reclaimed"] == 0
    assert result["zero_reclaim_reason"] == "active_work_claim"
    _still_held(conn)


def test_process_gone_holder_survives_startup_sweep(held_session):
    conn, hold = held_session
    hold(9872)
    conn.execute(
        "UPDATE harness_sessions SET native_process_gone_at=%s, "
        "native_process_gone_evidence=%s WHERE session_id='owner'",
        (_ago_minutes(500), json.dumps({"exit_code": 137})),
    )
    conn.commit()

    # Startup and periodic sweeps use the same persisted connection state.
    for _ in range(2):
        assert (
            clean_stale_harness_sessions(conn, stale_threshold_minutes=10)[
                "total_reclaimed"
            ]
            == 0
        )
        _still_held(conn)


def test_direct_stale_reclaim_refuses_and_explicit_end_releases(held_session):
    conn, hold = held_session
    hold(9873)

    with pytest.raises(SessionError, match="Release the claim"):
        reclaim_stale_session(conn, "owner")
    _still_held(conn)

    end_session(conn, "owner")
    claim = conn.execute(
        "SELECT released_at FROM work_claims WHERE session_id='owner'"
    ).fetchone()
    assert claim["released_at"] is not None
