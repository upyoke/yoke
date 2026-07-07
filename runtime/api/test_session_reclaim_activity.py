"""Direct coverage for the shared stale-reclaim activity classifier."""

from __future__ import annotations

import pytest

from yoke_core.domain.session_reclaim_activity import (
    REASON_ENDED,
    REASON_FRESH,
    REASON_HEARTBEAT_STALE,
    REASON_NEVER_ENGAGED,
    REASON_PROGRESS_STALE,
    classify_reclaimable,
    read_activity_signals,
    resolve_effective_ttl,
)
from runtime.api.test_sessions import _register, conn  # noqa: F401  (pytest fixture)
from runtime.api.sessions_api_stale_test_helpers import (
    _ago_minutes,
    _now_literal,
)


@pytest.fixture
def conn_with_events(conn):
    """Activity state lives on harness_sessions columns — no events table."""
    return conn


def _seed_session(
    conn,
    session_id: str,
    *,
    executor: str = "claude-code",
    heartbeat_ago_min: int = 0,
    ended_at: str = None,
):
    _register(conn, session_id=session_id, executor=executor)
    heartbeat_ts = _ago_minutes(heartbeat_ago_min) if heartbeat_ago_min > 0 else _now_literal()
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
    cursor = conn.execute(
        """INSERT INTO work_claims
           (session_id, target_kind, item_id, claim_type, claimed_at, last_heartbeat)
           VALUES (%s, 'item', %s, 'exclusive', %s, %s) RETURNING id""",
        (session_id, item_id, ts, ts),
    )
    claim_id = int(cursor.fetchone()[0])
    conn.commit()
    return claim_id


class TestResolveEffectiveTtl:
    def test_codex_uses_60_minute_override(self):
        # Codex sessions still use the configured override.
        assert resolve_effective_ttl("codex") == 60

    def test_claude_code_uses_default(self):
        assert resolve_effective_ttl("claude-code") == 20

    def test_unknown_executor_uses_default(self):
        assert resolve_effective_ttl("unknown") == 20


class TestReadActivitySignals:
    def test_returns_session_state_and_event_max(self, conn_with_events):
        c = conn_with_events
        _seed_session(c, "sess-A", heartbeat_ago_min=5)
        _emit_tool_event(c, "sess-A", ago_minutes=3)

        evidence = read_activity_signals(c, "sess-A")

        assert evidence.session_id == "sess-A"
        assert evidence.executor == "claude-code"
        assert evidence.effective_ttl_minutes == 20
        assert evidence.last_heartbeat is not None
        assert evidence.last_event_at is not None
        assert evidence.activity_at == max(
            evidence.last_heartbeat, evidence.last_event_at
        )
        assert evidence.ended_at is None

    def test_returns_claim_activity_when_claim_id_is_provided(
        self, conn_with_events,
    ):
        c = conn_with_events
        _seed_session(c, "sess-A", heartbeat_ago_min=30)
        claim_id = _seed_claim(c, "sess-A", item_id=7001, ago_minutes=2)

        evidence = read_activity_signals(c, "sess-A", claim_id=claim_id)

        assert evidence.claim_last_heartbeat is not None
        assert evidence.claim_claimed_at is not None
        assert evidence.activity_at == evidence.claim_last_heartbeat

    def test_unknown_session_returns_unknown_executor(self, conn_with_events):
        evidence = read_activity_signals(conn_with_events, "no-such-sess")
        assert evidence.executor == "unknown"
        assert evidence.last_heartbeat is None
        assert evidence.last_event_at is None
        assert evidence.activity_at is None


class TestClassifyReclaimable:
    def test_ended_session_is_reclaimable(self, conn_with_events):
        c = conn_with_events
        _seed_session(c, "ended-sess", heartbeat_ago_min=2, ended_at=_now_literal())
        _emit_tool_event(c, "ended-sess", ago_minutes=1)

        result = classify_reclaimable(c, "ended-sess")

        # Ended sessions reclaimable regardless of activity recency.
        assert result.is_reclaimable is True
        assert result.reason == REASON_ENDED

    def test_never_engaged_session(self, conn_with_events):
        c = conn_with_events
        # No session row at all → both signals None → never_engaged.
        result = classify_reclaimable(c, "ghost-sess")
        assert result.is_reclaimable is True
        assert result.reason == REASON_NEVER_ENGAGED

    def test_heartbeat_and_event_stale(self, conn_with_events):
        c = conn_with_events
        _seed_session(c, "stale-sess", heartbeat_ago_min=30)
        _emit_tool_event(c, "stale-sess", ago_minutes=25)

        result = classify_reclaimable(c, "stale-sess")

        assert result.is_reclaimable is True
        assert result.reason == REASON_HEARTBEAT_STALE

    def test_fresh_event_keeps_session_safe(self, conn_with_events):
        c = conn_with_events
        # Stale heartbeat but a fresh tool event keeps the session safe —
        # this is the silent-collision shape.
        _seed_session(c, "racy-sess", heartbeat_ago_min=30)
        _emit_tool_event(c, "racy-sess", ago_minutes=1)

        result = classify_reclaimable(c, "racy-sess")

        assert result.is_reclaimable is False
        assert result.reason == REASON_FRESH

    def test_fresh_heartbeat_keeps_session_safe(self, conn_with_events):
        c = conn_with_events
        _seed_session(c, "live-sess", heartbeat_ago_min=2)

        result = classify_reclaimable(c, "live-sess")

        assert result.is_reclaimable is False
        assert result.reason == REASON_FRESH

    def test_fresh_claim_heartbeat_keeps_session_safe(self, conn_with_events):
        c = conn_with_events
        _seed_session(c, "claim-live-sess", heartbeat_ago_min=30)
        claim_id = _seed_claim(
            c, "claim-live-sess", item_id=7002, ago_minutes=1,
        )

        result = classify_reclaimable(
            c, "claim-live-sess", claim_id=claim_id,
        )

        assert result.is_reclaimable is False
        assert result.reason == REASON_FRESH

    def test_progress_threshold_catches_wedged_session(self, conn_with_events):
        c = conn_with_events
        _seed_session(c, "wedged-sess", heartbeat_ago_min=1)
        _emit_tool_event(c, "wedged-sess", ago_minutes=120)

        result = classify_reclaimable(
            c, "wedged-sess", progress_threshold_minutes=90,
        )

        assert result.is_reclaimable is True
        assert result.reason == REASON_PROGRESS_STALE

    def test_codex_executor_uses_60_minute_override(self, conn_with_events):
        c = conn_with_events
        _seed_session(
            c, "codex-sess", executor="codex", heartbeat_ago_min=30,
        )
        _emit_tool_event(c, "codex-sess", ago_minutes=30)

        result = classify_reclaimable(c, "codex-sess")

        # 30 minutes of silence is fresh under the codex 60-minute TTL.
        assert result.is_reclaimable is False
        assert result.evidence.effective_ttl_minutes == 60

    def test_codex_executor_reclaims_after_60_minutes(self, conn_with_events):
        c = conn_with_events
        _seed_session(
            c, "codex-stale", executor="codex", heartbeat_ago_min=120,
        )
        _emit_tool_event(c, "codex-stale", ago_minutes=120)

        result = classify_reclaimable(c, "codex-stale")

        assert result.is_reclaimable is True
        assert result.reason == REASON_HEARTBEAT_STALE
