# ruff: noqa: E402, F401, F811
"""Shared setup for tests in this directory."""

from __future__ import annotations

import pytest

from yoke_contracts.timestamps import parse_instant

from yoke_core.domain.session_reclaim_activity import (
    REASON_ENDED,
    REASON_FRESH,
    REASON_ACTIVE_WORK_CLAIM,
    REASON_HEARTBEAT_STALE,
    REASON_NEVER_ENGAGED,
    REASON_PROGRESS_STALE,
    classify_reclaimable,
    read_activity_signals,
    resolve_effective_ttl,
)

from yoke_core.domain.session_reclaim_progress import (
    current_episode_progress_stamp,
)

from runtime.api.sessions_test_support import _register, conn  # noqa: F401  (pytest fixture)

from runtime.api.sessions_api_stale_test_helpers import (
    _ago_minutes,
    _now_instant,
)

from yoke_core.domain.work_claim_targets import make_item_target


def _seed_session(
    conn,
    session_id: str,
    *,
    executor: str = "claude-code",
    heartbeat_ago_min: int = 0,
    ended_at: str = None,
):
    _register(conn, session_id=session_id, executor=executor)
    heartbeat_ts = (
        _ago_minutes(heartbeat_ago_min) if heartbeat_ago_min > 0 else _now_instant()
    )
    conn.execute(
        """UPDATE harness_sessions
           SET offered_at = %s, last_heartbeat = %s, ended_at = %s
           WHERE session_id = %s""",
        (heartbeat_ts, heartbeat_ts, ended_at, session_id),
    )
    conn.commit()


def _emit_tool_event(conn, session_id: str, ago_minutes: int) -> None:
    """Stamp the tool-activity columns the observe pipeline maintains."""
    conn.execute(
        """UPDATE harness_sessions
           SET last_tool_call_at = %s,
               tool_call_count = COALESCE(tool_call_count, 0) + 1
           WHERE session_id = %s""",
        (_ago_minutes(ago_minutes), session_id),
    )
    conn.commit()


def _seed_claim(conn, session_id: str, item_id: int, ago_minutes: int) -> int:
    ts = _ago_minutes(ago_minutes)
    target = make_item_target(item_id)
    cursor = conn.execute(
        """INSERT INTO work_claims
           (session_id, target_kind, scope, claim_type, claimed_at, last_heartbeat)
           VALUES (%s, %s, %s, 'exclusive', %s, %s) RETURNING id""",
        (session_id, target.kind, target.scope_json(), ts, ts),
    )
    claim_id = int(cursor.fetchone()[0])
    conn.commit()
    return claim_id
