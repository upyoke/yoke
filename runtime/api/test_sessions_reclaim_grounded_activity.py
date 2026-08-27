# ruff: noqa: F811
"""Idle sessions are collected whatever their harness leaves behind.

Two converging defects kept an archived session alive forever. An unfinished
``session_tool_calls`` row reported the session as permanently in flight, so no
amount of idleness reached the reclaim; and the chain checkpoint it left behind
then refused every later end attempt with ``chain_pending``. Neither defect is
specific to one executor, so every case here runs across surfaces.
"""

from __future__ import annotations

import pytest

from runtime.api.sessions_api_stale_test_helpers import _ago_minutes
from runtime.api.test_session_reclaim_activity import (  # noqa: F401
    _emit_tool_event,
    _seed_session,
)
from runtime.api.test_sessions import conn  # noqa: F401
from yoke_core.domain.session_reclaim_activity import (
    REASON_FRESH,
    REASON_HEARTBEAT_STALE,
    classify_reclaimable,
    read_activity_signals,
    resolve_effective_ttl,
)
from yoke_core.domain.session_reclaim_progress import open_tool_call_is_live
from yoke_core.domain.sessions_analytics_core import (
    DEFAULT_STALE_THRESHOLD_MINUTES,
)
from yoke_core.domain.sessions_cleanup import clean_stale_harness_sessions
from yoke_core.domain.sessions_queries import (
    read_chain_checkpoint,
    update_chain_checkpoint,
)
from yoke_core.domain.sessions_render_end_if_empty import end_session_if_empty
from yoke_core.domain.sessions_render_reclaim import reclaim_stale_session

# Both executors in the diagnosed runs share the same short TTL.
EXECUTORS = ("codex", "claude-code")

# How far the leftover row predates the session's newest recorded activity.
# Any gap wider than the harness write skew proves the row is residue.
RESIDUE_LEAD_MINUTES = 30


def _idle_minutes(executor: str) -> int:
    """Idle past the executor's TTL but inside the in-flight hard window.

    Staying inside the hard window is the point: a session the hard window
    would collect anyway proves nothing about the grounding under test.
    """
    return resolve_effective_ttl(executor) + 5


def _open_tool_call(conn, session_id: str, ago_minutes: int) -> None:
    conn.execute(
        "INSERT INTO session_tool_calls "
        "(session_id, tool_use_id, tool_name, started_at) "
        "VALUES (%s, %s, 'Bash', %s)",
        (session_id, f"open-{session_id}", _ago_minutes(ago_minutes)),
    )
    conn.commit()


def _seed_idle_session_with_leftover_row(conn, executor: str) -> tuple[str, int]:
    """Seed the diagnosed shape: idle past TTL, one never-closed tool call."""
    idle = _idle_minutes(executor)
    session_id = f"idle-{executor}"
    _seed_session(conn, session_id, executor=executor, heartbeat_ago_min=idle)
    _emit_tool_event(conn, session_id, ago_minutes=idle)
    _open_tool_call(conn, session_id, ago_minutes=idle + RESIDUE_LEAD_MINUTES)
    return session_id, idle


class TestOpenToolCallGrounding:
    def test_live_call_counts_and_leftover_row_does_not(self):
        now = _ago_minutes(0)
        assert open_tool_call_is_live(now, now) is True
        assert open_tool_call_is_live(_ago_minutes(90), _ago_minutes(60)) is False
        assert open_tool_call_is_live(None, now) is False
        assert open_tool_call_is_live(now, None) is True

    @pytest.mark.parametrize("executor", EXECUTORS)
    def test_leftover_row_does_not_shield_an_idle_session(self, conn, executor):
        session_id, _idle = _seed_idle_session_with_leftover_row(conn, executor)

        evidence = read_activity_signals(conn, session_id)
        result = classify_reclaimable(conn, session_id)

        assert evidence.open_tool_call_at is not None
        assert evidence.open_tool_call_live is False
        assert evidence.in_flight is False
        assert result.is_reclaimable is True
        assert result.reason == REASON_HEARTBEAT_STALE

    @pytest.mark.parametrize("executor", EXECUTORS)
    def test_a_call_that_is_the_newest_activity_still_shields(self, conn, executor):
        idle = _idle_minutes(executor)
        session_id = f"working-{executor}"
        _seed_session(conn, session_id, executor=executor, heartbeat_ago_min=idle)
        _emit_tool_event(conn, session_id, ago_minutes=idle)
        _open_tool_call(conn, session_id, ago_minutes=idle)

        result = classify_reclaimable(conn, session_id)

        assert result.evidence.open_tool_call_live is True
        assert result.is_reclaimable is False
        assert result.reason == REASON_FRESH


class TestSweepCollectsIdleSessions:
    @pytest.mark.parametrize("executor", EXECUTORS)
    def test_idle_session_is_reclaimed_and_reports_real_staleness(
        self, conn, executor
    ):
        session_id, idle = _seed_idle_session_with_leftover_row(conn, executor)

        result = clean_stale_harness_sessions(conn)

        collected = [
            entry
            for entry in result["heartbeat_stale"]
            if entry["session_id"] == session_id
        ]
        assert collected, result
        assert collected[0]["stale_minutes"] >= idle
        assert not [
            entry
            for entry in result["skipped_between_turns"]
            if entry["session_id"] == session_id
        ]
        ended_at = conn.execute(
            "SELECT ended_at FROM harness_sessions WHERE session_id = %s",
            (session_id,),
        ).fetchone()["ended_at"]
        assert ended_at is not None

    @pytest.mark.parametrize("executor", EXECUTORS)
    def test_a_spared_session_is_explained_on_every_surface(self, conn, executor):
        """Past the base threshold, spared, and reported — whatever the surface.

        Both surfaces are spared by a live tool call and deserve the same
        explanation in the result.
        """
        session_id = f"spared-{executor}"
        idle = DEFAULT_STALE_THRESHOLD_MINUTES + 5
        _seed_session(conn, session_id, executor=executor, heartbeat_ago_min=idle)
        _emit_tool_event(conn, session_id, ago_minutes=idle)
        _open_tool_call(conn, session_id, ago_minutes=idle)

        result = clean_stale_harness_sessions(conn)

        assert [
            entry
            for entry in result["skipped_between_turns"]
            if entry["session_id"] == session_id
        ], result


class TestChainBudgetDiesWithTheSession:
    @pytest.mark.parametrize("executor", EXECUTORS)
    def test_reclaim_clears_the_chain_checkpoint(self, conn, executor):
        session_id, _idle = _seed_idle_session_with_leftover_row(conn, executor)
        update_chain_checkpoint(
            conn,
            session_id,
            step=2,
            action="advance",
            chainable=True,
        )
        assert read_chain_checkpoint(conn, session_id) is not None

        reclaim_stale_session(conn, session_id)

        assert read_chain_checkpoint(conn, session_id) is None

    @pytest.mark.parametrize("executor", EXECUTORS)
    def test_reclaimed_checkpoint_no_longer_refuses_the_empty_end(
        self, conn, executor
    ):
        session_id, _idle = _seed_idle_session_with_leftover_row(conn, executor)
        update_chain_checkpoint(
            conn,
            session_id,
            step=2,
            action="advance",
            chainable=True,
        )
        assert end_session_if_empty(conn, session_id)["status"] == "chain_pending"

        reclaim_stale_session(conn, session_id)
        # A reactivated episode reuses the same row, so the checkpoint would
        # come back with it if the reclaim had left it in place.
        conn.execute(
            "UPDATE harness_sessions SET ended_at = NULL WHERE session_id = %s",
            (session_id,),
        )
        conn.commit()

        assert end_session_if_empty(conn, session_id)["status"] == "ended"
