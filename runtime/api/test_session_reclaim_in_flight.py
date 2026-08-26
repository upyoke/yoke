# ruff: noqa: F811
"""In-flight turns and open tool calls must not lose their work claims.

Diagnosed shape: a live claude-cli worker was reclaimed as heartbeat_stale
after 23 quiet minutes while its native turn was still running, then
reactivation ignored release_reason=reclaimed so the loss stayed silent.
"""

from __future__ import annotations

import pytest

from runtime.api.sessions_api_stale_test_helpers import _ago_minutes, _now_literal
from runtime.api.test_session_reclaim_activity import (
    _emit_tool_event,
    _seed_claim,
    _seed_session,
)
from runtime.api.test_sessions import _insert_claimable_item, conn  # noqa: F401
from yoke_core.domain.session_reclaim_activity import (
    IN_FLIGHT_HARD_TTL_MULTIPLIER,
    REASON_ABANDONED_IN_FLIGHT,
    REASON_FRESH,
    REASON_HEARTBEAT_STALE,
    REASON_PROGRESS_STALE,
    classify_reclaimable,
    latest_activity,
    read_activity_signals,
    resolve_effective_ttl,
)
from yoke_core.domain.session_reclaim_activity_bulk import latest_activity_by_session
from yoke_core.domain.session_staleness import activity_is_stale
from yoke_core.domain.sessions import (
    claim_work,
    clean_stale_harness_sessions,
)
from yoke_core.domain.sessions_lifecycle_reactivation_claims import (
    auto_reacquire_session_ended_claims,
)
from yoke_core.domain.work_claim_targets import make_item_target


@pytest.fixture
def conn_with_events(conn):
    """Session reclaim tests need turn_posture; the shared fixture omits it."""
    from yoke_core.domain.schema_common import _get_columns

    columns = set(_get_columns(conn, "harness_sessions"))
    if "turn_posture" not in columns:
        conn.execute(
            "ALTER TABLE harness_sessions "
            "ADD COLUMN turn_posture TEXT NOT NULL DEFAULT 'unknown'"
        )
        conn.commit()
    return conn


def _set_turn_posture(conn, session_id: str, posture: str) -> None:
    conn.execute(
        "UPDATE harness_sessions SET turn_posture = %s WHERE session_id = %s",
        (posture, session_id),
    )
    conn.commit()


def _open_tool_call(conn, session_id: str, ago_minutes: int) -> None:
    conn.execute(
        "INSERT INTO session_tool_calls "
        "(session_id, tool_use_id, tool_name, started_at) "
        "VALUES (%s, %s, 'Bash', %s)",
        (session_id, f"tool-{session_id}", _ago_minutes(ago_minutes)),
    )
    conn.commit()


class TestInFlightReclaim:
    def test_running_turn_with_stale_heartbeats_is_fresh(self, conn_with_events):
        c = conn_with_events
        _seed_session(c, "running-dash", heartbeat_ago_min=30)
        _emit_tool_event(c, "running-dash", ago_minutes=24)
        _set_turn_posture(c, "running-dash", "running")

        result = classify_reclaimable(c, "running-dash")

        assert result.is_reclaimable is False
        assert result.reason == REASON_FRESH
        assert result.evidence.turn_posture == "running"
        assert not activity_is_stale(
            latest_activity(c, "running-dash"),
            executor="claude-code",
        )

    def test_open_tool_call_with_stale_heartbeats_is_fresh(self, conn_with_events):
        c = conn_with_events
        _seed_session(c, "long-bash", heartbeat_ago_min=30)
        _emit_tool_event(c, "long-bash", ago_minutes=25)
        _open_tool_call(c, "long-bash", ago_minutes=25)

        result = classify_reclaimable(c, "long-bash")

        assert result.is_reclaimable is False
        assert result.reason == REASON_FRESH
        assert result.evidence.open_tool_call is True

    def test_waiting_turn_with_stale_heartbeats_is_reclaimable(self, conn_with_events):
        c = conn_with_events
        _seed_session(c, "idle-dash", heartbeat_ago_min=30)
        _emit_tool_event(c, "idle-dash", ago_minutes=25)
        _set_turn_posture(c, "idle-dash", "waiting")

        result = classify_reclaimable(c, "idle-dash")

        assert result.is_reclaimable is True
        assert result.reason == REASON_HEARTBEAT_STALE

    def test_running_turn_still_progress_stale_without_open_tool(
        self, conn_with_events
    ):
        c = conn_with_events
        _seed_session(c, "wedged-running", heartbeat_ago_min=30)
        _emit_tool_event(c, "wedged-running", ago_minutes=120)
        _set_turn_posture(c, "wedged-running", "running")
        c.execute(
            "UPDATE harness_sessions SET episode_started_at = %s "
            "WHERE session_id = 'wedged-running'",
            (_ago_minutes(120),),
        )
        c.commit()

        result = classify_reclaimable(
            c,
            "wedged-running",
            progress_threshold_minutes=90,
        )

        assert result.is_reclaimable is True
        assert result.reason == REASON_PROGRESS_STALE

    def test_open_tool_call_is_reclaimable_after_the_hard_ttl(self, conn_with_events):
        c = conn_with_events
        old_minutes = (
            resolve_effective_ttl("claude-code") * IN_FLIGHT_HARD_TTL_MULTIPLIER + 1
        )
        _seed_session(c, "hour-pytest", heartbeat_ago_min=old_minutes)
        _emit_tool_event(c, "hour-pytest", ago_minutes=old_minutes)
        _open_tool_call(c, "hour-pytest", ago_minutes=old_minutes)
        c.execute(
            "UPDATE harness_sessions SET episode_started_at = %s "
            "WHERE session_id = 'hour-pytest'",
            (_ago_minutes(old_minutes),),
        )
        c.commit()

        result = classify_reclaimable(
            c,
            "hour-pytest",
            progress_threshold_minutes=90,
        )

        assert result.is_reclaimable is True
        assert result.reason == REASON_ABANDONED_IN_FLIGHT


class TestInFlightSweepAndScheduler:
    def test_cleanup_leaves_running_session_claim_intact(self, conn_with_events):
        c = conn_with_events
        _insert_claimable_item(c, 9101)
        _seed_session(c, "live-worker", heartbeat_ago_min=0)
        claim_work(c, session_id="live-worker", item_id=9101)
        old = _ago_minutes(30)
        c.execute(
            "UPDATE harness_sessions SET offered_at=%s, last_heartbeat=%s, "
            "last_tool_call_at=%s, turn_posture='running' "
            "WHERE session_id='live-worker'",
            (old, old, _ago_minutes(24)),
        )
        c.execute(
            "UPDATE work_claims SET claimed_at=%s, last_heartbeat=%s "
            "WHERE session_id='live-worker' AND released_at IS NULL",
            (old, old),
        )
        c.commit()

        clean_stale_harness_sessions(c)

        target = make_item_target(9101)
        row = c.execute(
            "SELECT released_at, release_reason FROM work_claims "
            "WHERE session_id = 'live-worker' AND target_kind = %s "
            "AND scope = %s ORDER BY id DESC LIMIT 1",
            (target.kind, target.scope_json()),
        ).fetchone()
        assert row["released_at"] is None
        assert row["release_reason"] is None

    def test_bulk_activity_treats_running_turn_as_live(self, conn_with_events):
        c = conn_with_events
        _seed_session(c, "bulk-running", heartbeat_ago_min=30)
        _emit_tool_event(c, "bulk-running", ago_minutes=24)
        _set_turn_posture(c, "bulk-running", "running")

        activity = latest_activity_by_session(c, ["bulk-running"])

        assert not activity_is_stale(
            activity["bulk-running"],
            executor="claude-code",
        )

    def test_bulk_activity_stops_masking_an_abandoned_turn(self, conn_with_events):
        c = conn_with_events
        old_minutes = 20 * IN_FLIGHT_HARD_TTL_MULTIPLIER + 1
        _seed_session(c, "bulk-abandoned", heartbeat_ago_min=old_minutes)
        _emit_tool_event(c, "bulk-abandoned", ago_minutes=old_minutes)
        _set_turn_posture(c, "bulk-abandoned", "running")

        activity = latest_activity_by_session(c, ["bulk-abandoned"])

        assert activity_is_stale(activity["bulk-abandoned"], executor="claude-code")

    def test_cleanup_reclaims_an_abandoned_running_session_claim(
        self, conn_with_events
    ):
        c = conn_with_events
        _insert_claimable_item(c, 9103)
        old_minutes = 20 * IN_FLIGHT_HARD_TTL_MULTIPLIER + 1
        _seed_session(c, "abandoned-worker", heartbeat_ago_min=old_minutes)
        claim_work(c, session_id="abandoned-worker", item_id=9103)
        old = _ago_minutes(old_minutes)
        c.execute(
            "UPDATE harness_sessions SET offered_at=%s,last_heartbeat=%s,"
            "last_tool_call_at=%s,turn_posture='running' "
            "WHERE session_id='abandoned-worker'",
            (old, old, old),
        )
        c.execute(
            "UPDATE work_claims SET claimed_at=%s,last_heartbeat=%s "
            "WHERE session_id='abandoned-worker' AND released_at IS NULL",
            (old, old),
        )
        c.commit()

        clean_stale_harness_sessions(c)

        target = make_item_target(9103)
        row = c.execute(
            "SELECT released_at,release_reason FROM work_claims "
            "WHERE session_id='abandoned-worker' AND target_kind = %s "
            "AND scope = %s",
            (target.kind, target.scope_json()),
        ).fetchone()
        assert row["released_at"] is not None
        assert row["release_reason"] == "reclaimed"


class TestReclaimedClaimReactivation:
    def test_reacquire_restores_recent_reclaimed_claim(self, conn_with_events):
        c = conn_with_events
        _insert_claimable_item(c, 9102)
        _seed_session(c, "resume-worker", heartbeat_ago_min=1)
        claim_id = _seed_claim(c, "resume-worker", item_id=9102, ago_minutes=1)
        now = _now_literal()
        c.execute(
            "UPDATE work_claims SET released_at = %s, release_reason = 'reclaimed' "
            "WHERE id = %s",
            (now, claim_id),
        )
        c.commit()

        reacquired, conflicts = auto_reacquire_session_ended_claims(
            c,
            "resume-worker",
            reacquire_window_s=300,
        )

        assert conflicts == []
        assert len(reacquired) == 1
        assert reacquired[0]["target_kind"] == "item"
        assert reacquired[0]["scope"] == {"item_id": 9102}
        target = make_item_target(9102)
        active = c.execute(
            "SELECT COUNT(*) AS n FROM work_claims "
            "WHERE session_id = 'resume-worker' AND target_kind = %s "
            "AND scope = %s AND released_at IS NULL",
            (target.kind, target.scope_json()),
        ).fetchone()
        assert int(active["n"] if hasattr(active, "keys") else active[0]) == 1

    def test_read_activity_signals_reports_in_flight_flags(self, conn_with_events):
        c = conn_with_events
        _seed_session(c, "flag-sess", heartbeat_ago_min=5)
        _set_turn_posture(c, "flag-sess", "running")
        _open_tool_call(c, "flag-sess", ago_minutes=2)

        evidence = read_activity_signals(c, "flag-sess")

        assert evidence.in_flight is True
        assert evidence.open_tool_call is True
        payload = evidence.as_payload()
        assert payload["turn_posture"] == "running"
        assert payload["open_tool_call"] is True
