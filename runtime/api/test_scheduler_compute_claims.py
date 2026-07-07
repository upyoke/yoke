"""Focused scheduler claim-staleness tests."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from yoke_core.domain.scheduler import (
    ClaimState,
    _evaluate_claim_states,
    compute_schedule,
)
from runtime.api.scheduler_test_fixtures import (  # noqa: F401
    _create_sml_files,
    _item_num,
    scheduler_db,
)


def _iso(minutes_ago: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )


def _claim_top_item(conn, tmp_dir, *, session_id: str, executor: str, minutes_ago: int) -> str:
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
    _create_sml_files(tmp_dir)
    baseline = compute_schedule(conn, project_scope=["yoke"], workspace=tmp_dir)
    assert baseline.selected_step is not None
    top_item = baseline.selected_step.item_id
    conn.execute(
        """INSERT INTO work_claims
           (session_id, target_kind, item_id, claim_type, claimed_at, last_heartbeat)
           VALUES (%s, 'item', %s, 'exclusive', %s, %s)""",
        (session_id, _item_num(top_item), seen_at, seen_at),
    )
    conn.commit()
    return top_item


def test_claude_desktop_19_minute_claim_is_live(scheduler_db):
    conn = scheduler_db["conn"]
    top_item = _claim_top_item(
        conn,
        scheduler_db["tmp_dir"],
        session_id="claude-owner",
        executor="claude-desktop",
        minutes_ago=19,
    )

    claims = _evaluate_claim_states(conn, [top_item])
    assert claims[top_item] == ClaimState.CLAIMED_BY_OTHER_LIVE

    result = compute_schedule(conn, project_scope=["yoke"], workspace=scheduler_db["tmp_dir"])
    if result.selected_step is not None:
        assert result.selected_step.item_id != top_item


def test_codex_45_minute_claim_uses_executor_ttl_override(scheduler_db):
    conn = scheduler_db["conn"]
    top_item = _claim_top_item(
        conn,
        scheduler_db["tmp_dir"],
        session_id="codex-owner",
        executor="codex-desktop",
        minutes_ago=45,
    )

    claims = _evaluate_claim_states(conn, [top_item])
    assert claims[top_item] == ClaimState.CLAIMED_BY_OTHER_LIVE

    result = compute_schedule(conn, project_scope=["yoke"], workspace=scheduler_db["tmp_dir"])
    if result.selected_step is not None:
        assert result.selected_step.item_id != top_item


def test_codex_65_minute_claim_is_stale_and_selectable(scheduler_db):
    conn = scheduler_db["conn"]
    top_item = _claim_top_item(
        conn,
        scheduler_db["tmp_dir"],
        session_id="codex-stale",
        executor="codex-desktop",
        minutes_ago=65,
    )

    claims = _evaluate_claim_states(conn, [top_item])
    assert claims[top_item] == ClaimState.CLAIMED_BY_STALE

    result = compute_schedule(conn, project_scope=["yoke"], workspace=scheduler_db["tmp_dir"])
    assert result.selected_step is not None
    assert result.selected_step.item_id == top_item
