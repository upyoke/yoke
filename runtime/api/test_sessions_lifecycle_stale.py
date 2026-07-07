"""Stale-session detection, handoff transfer, and transaction-safety tests."""

from __future__ import annotations

import pytest

from runtime.api.test_sessions import (
    _register,
    conn,  # noqa: F401  (pytest fixture)
)
from yoke_core.domain.sessions import (
    SessionError,
    claim_work,
    end_session,
    find_stale_sessions,
    handoff_claim,
    reclaim_stale_session,
    release_claim,
)


# ---------------------------------------------------------------------------
# Stale detection tests
# ---------------------------------------------------------------------------


class TestStaleDetection:
    def test_fresh_session_not_stale(self, conn):
        _register(conn)
        stale = find_stale_sessions(conn, stale_threshold_minutes=10)
        assert len(stale) == 0

    def test_old_session_is_stale(self, conn):
        _register(conn)
        # Manually set heartbeat to far in the past
        conn.execute(
            "UPDATE harness_sessions SET last_heartbeat = '2020-01-01T00:00:00Z' WHERE session_id='sess-1'"
        )
        conn.commit()
        stale = find_stale_sessions(conn, stale_threshold_minutes=10)
        assert len(stale) == 1
        assert stale[0]["session_id"] == "sess-1"

    def test_same_day_iso_heartbeat_is_stale(self, conn):
        from datetime import datetime, timedelta, timezone
        _register(conn)
        stale_iso = (datetime.now(timezone.utc) - timedelta(minutes=30)).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        )
        conn.execute(
            "UPDATE harness_sessions SET last_heartbeat = %s WHERE session_id='sess-1'",
            (stale_iso,),
        )
        conn.commit()
        stale = find_stale_sessions(conn, stale_threshold_minutes=10)
        assert len(stale) == 1
        assert stale[0]["session_id"] == "sess-1"

    def test_ended_session_not_stale(self, conn):
        _register(conn)
        conn.execute(
            "UPDATE harness_sessions SET last_heartbeat = '2020-01-01T00:00:00Z' WHERE session_id='sess-1'"
        )
        end_session(conn, "sess-1")  # no claims, should succeed
        stale = find_stale_sessions(conn, stale_threshold_minutes=10)
        assert len(stale) == 0

    def test_reclaim_stale_session(self, conn):
        _register(conn)
        claim_work(conn, session_id="sess-1", item_id="YOK-9999")
        conn.execute(
            "UPDATE harness_sessions SET last_heartbeat = '2020-01-01T00:00:00Z' WHERE session_id='sess-1'"
        )
        conn.commit()
        result = reclaim_stale_session(conn, "sess-1")
        assert result["ended_at"] is not None
        # Claim should be released with reason reclaimed
        claim = conn.execute(
            "SELECT release_reason FROM work_claims WHERE session_id='sess-1'"
        ).fetchone()
        assert claim["release_reason"] == "reclaimed"


# ---------------------------------------------------------------------------
# Handoff tests
# ---------------------------------------------------------------------------


class TestHandoff:
    def test_handoff_transfers_claim(self, conn):
        _register(conn, session_id="sess-1")
        _register(conn, session_id="sess-2")
        c = claim_work(conn, session_id="sess-1", item_id="YOK-9999")
        new_claim = handoff_claim(conn, c["id"], "sess-2")
        assert new_claim["session_id"] == "sess-2"
        assert new_claim["item_id"] == 9999
        # Old claim should be handed_off
        old = conn.execute(
            "SELECT release_reason FROM work_claims WHERE id = %s", (c["id"],)
        ).fetchone()
        assert old["release_reason"] == "handed_off"

    def test_handoff_to_ended_session_fails(self, conn):
        _register(conn, session_id="sess-1")
        _register(conn, session_id="sess-2")
        c = claim_work(conn, session_id="sess-1", item_id="YOK-9999")
        end_session(conn, "sess-2")
        with pytest.raises(SessionError) as exc_info:
            handoff_claim(conn, c["id"], "sess-2")
        assert exc_info.value.code == "SESSION_ENDED"

    def test_handoff_released_claim_fails(self, conn):
        _register(conn, session_id="sess-1")
        _register(conn, session_id="sess-2")
        c = claim_work(conn, session_id="sess-1", item_id="YOK-9999")
        release_claim(conn, c["id"])
        with pytest.raises(SessionError) as exc_info:
            handoff_claim(conn, c["id"], "sess-2")
        assert exc_info.value.code == "ALREADY_RELEASED"

    def test_handoff_nonexistent_target_fails(self, conn):
        _register(conn, session_id="sess-1")
        c = claim_work(conn, session_id="sess-1", item_id="YOK-9999")
        with pytest.raises(SessionError) as exc_info:
            handoff_claim(conn, c["id"], "ghost")
        assert exc_info.value.code == "NOT_FOUND"


# ---------------------------------------------------------------------------
# Transaction safety
# ---------------------------------------------------------------------------


class TestTransactionSafety:
    def test_register_is_committed(self, conn):
        _register(conn)
        # Verify by reading directly
        row = conn.execute("SELECT COUNT(*) as cnt FROM harness_sessions").fetchone()
        assert row["cnt"] == 1

    def test_claim_is_committed(self, conn):
        _register(conn)
        claim_work(conn, session_id="sess-1", item_id="YOK-9999")
        row = conn.execute("SELECT COUNT(*) as cnt FROM work_claims").fetchone()
        assert row["cnt"] == 1

    def test_end_session_atomicity_no_claims(self, conn):
        """End session with no active claims marks session ended."""
        _register(conn)
        c1 = claim_work(conn, session_id="sess-1", item_id="YOK-1")
        c2 = claim_work(conn, session_id="sess-1", item_id="YOK-2")
        release_claim(conn, c1["id"], reason="completed")
        release_claim(conn, c2["id"], reason="completed")
        end_session(conn, "sess-1")
        session = conn.execute(
            "SELECT ended_at FROM harness_sessions WHERE session_id='sess-1'"
        ).fetchone()
        assert session["ended_at"] is not None

    def test_end_session_atomicity_releases_claims_then_ends(self, conn):
        """No-flags end_session releases active claims and ends atomically.

        Contract change: the prior ACTIVE_CLAIM rejection is replaced
        by an auto-release through the typed work-claim release path.
        The session row and the per-claim release payload land in the
        same successful response.
        """
        _register(conn)
        claim_work(conn, session_id="sess-1", item_id="YOK-1")
        claim_work(conn, session_id="sess-1", item_id="YOK-2")
        result = end_session(conn, "sess-1")
        session = conn.execute(
            "SELECT ended_at FROM harness_sessions WHERE session_id='sess-1'"
        ).fetchone()
        assert session["ended_at"] is not None
        active = conn.execute(
            "SELECT COUNT(*) as cnt FROM work_claims "
            "WHERE session_id='sess-1' AND released_at IS NULL"
        ).fetchone()
        assert active["cnt"] == 0
        assert len(result["released_claims"]) == 2
