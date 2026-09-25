# ruff: noqa: F401, F811
"""Focused scheduler claim-staleness tests."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from yoke_core.domain.scheduler import (
    ClaimState,
    _evaluate_claim_states,
    compute_schedule,
)
from runtime.api.scheduler_test_fixtures import (  # noqa: F401
    _item_num,
    scheduler_db,
)
from yoke_core.domain.work_claim_targets import make_item_target


def _iso(minutes_ago: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )


def _claim_top_item(conn, *, session_id: str, executor: str, minutes_ago: int) -> str:
    seen_at = _iso(minutes_ago)
    conn.execute(
        """INSERT INTO harness_sessions
           (session_id, executor, provider, model, workspace, offered_at, last_heartbeat)
           VALUES (%s, %s, 'anthropic', 'claude', '/tmp', %s, %s)""",
        (session_id, executor, seen_at, seen_at),
    )
    # ``compute_schedule`` may roll back optional-probe failures; keep the
    # owner session durable before using it to choose the item to claim.
    conn.commit()
    baseline = compute_schedule(conn, project_scope=["yoke"])
    assert baseline.selected_step is not None
    top_item = baseline.selected_step.item_id
    target = make_item_target(_item_num(top_item))
    conn.execute(
        """INSERT INTO work_claims
           (session_id, target_kind, scope, claim_type, claimed_at, last_heartbeat)
           VALUES (%s, %s, %s, 'exclusive', %s, %s)""",
        (session_id, target.kind, target.scope_json(), seen_at, seen_at),
    )
    conn.commit()
    return top_item


def test_claude_desktop_19_minute_claim_is_live(scheduler_db):
    conn = scheduler_db["conn"]
    top_item = _claim_top_item(
        conn,
        session_id="claude-owner",
        executor="claude-desktop",
        minutes_ago=19,
    )

    claims = _evaluate_claim_states(conn, [top_item])
    assert claims[top_item] == ClaimState.CLAIMED_BY_OTHER_LIVE

    result = compute_schedule(conn, project_scope=["yoke"])
    if result.selected_step is not None:
        assert result.selected_step.item_id != top_item


def test_fifteen_minute_claim_is_still_live(scheduler_db):
    conn = scheduler_db["conn"]
    top_item = _claim_top_item(
        conn,
        session_id="fresh-owner",
        executor="codex-desktop",
        minutes_ago=15,
    )

    claims = _evaluate_claim_states(conn, [top_item])
    assert claims[top_item] == ClaimState.CLAIMED_BY_OTHER_LIVE

    result = compute_schedule(conn, project_scope=["yoke"])
    if result.selected_step is not None:
        assert result.selected_step.item_id != top_item


def test_twenty_five_minute_claim_remains_held(scheduler_db):
    conn = scheduler_db["conn"]
    top_item = _claim_top_item(
        conn,
        session_id="codex-stale",
        executor="codex-desktop",
        minutes_ago=25,
    )

    claims = _evaluate_claim_states(conn, [top_item])
    assert claims[top_item] == ClaimState.CLAIMED_BY_OTHER_LIVE

    result = compute_schedule(conn, project_scope=["yoke"])
    if result.selected_step is not None:
        assert result.selected_step.item_id != top_item


def _park(conn, session_id: str) -> None:
    conn.execute(
        "UPDATE harness_sessions SET mode = 'parked' WHERE session_id = %s",
        (session_id,),
    )
    conn.commit()


def test_parked_holder_past_ttl_stays_live(scheduler_db):
    """A worker parked on purpose keeps its claim however long it waits."""
    conn = scheduler_db["conn"]
    top_item = _claim_top_item(
        conn,
        session_id="parked-owner",
        executor="claude-code",
        minutes_ago=240,
    )
    _park(conn, "parked-owner")

    claims = _evaluate_claim_states(conn, [top_item])
    assert claims[top_item] == ClaimState.CLAIMED_BY_OTHER_LIVE

    result = compute_schedule(conn, project_scope=["yoke"])
    if result.selected_step is not None:
        assert result.selected_step.item_id != top_item


def test_ended_parked_holder_is_stale(scheduler_db):
    """The park protects a wait, not a session that is over."""
    conn = scheduler_db["conn"]
    top_item = _claim_top_item(
        conn,
        session_id="parked-ended",
        executor="claude-code",
        minutes_ago=240,
    )
    _park(conn, "parked-ended")
    conn.execute(
        "UPDATE harness_sessions SET ended_at = %s WHERE session_id = %s",
        (_iso(30), "parked-ended"),
    )
    conn.commit()

    claims = _evaluate_claim_states(conn, [top_item])
    assert claims[top_item] == ClaimState.CLAIMED_BY_STALE


def test_parked_holder_with_dead_native_remains_held(scheduler_db):
    """A missing native process does not release persisted ownership."""
    conn = scheduler_db["conn"]
    top_item = _claim_top_item(
        conn,
        session_id="parked-crashed",
        executor="claude-code",
        minutes_ago=240,
    )
    _park(conn, "parked-crashed")
    conn.execute(
        "UPDATE harness_sessions SET native_process_gone_at = %s, "
        "native_process_gone_evidence = %s WHERE session_id = %s",
        (_iso(60), '{"pids": [4242], "exit_code": 137}', "parked-crashed"),
    )
    conn.commit()

    claims = _evaluate_claim_states(conn, [top_item])
    assert claims[top_item] == ClaimState.CLAIMED_BY_OTHER_LIVE


def test_parked_holder_whose_native_finished_cleanly_stays_live(scheduler_db):
    """A headless command that exited 0 under a park ended its turn, not the wait."""
    conn = scheduler_db["conn"]
    top_item = _claim_top_item(
        conn,
        session_id="parked-finished",
        executor="claude-code",
        minutes_ago=240,
    )
    _park(conn, "parked-finished")
    conn.execute(
        "UPDATE harness_sessions SET native_process_gone_at = %s, "
        "native_process_gone_evidence = %s WHERE session_id = %s",
        (_iso(60), '{"pids": [4243], "exit_code": 0}', "parked-finished"),
    )
    conn.commit()

    claims = _evaluate_claim_states(conn, [top_item])
    assert claims[top_item] == ClaimState.CLAIMED_BY_OTHER_LIVE
