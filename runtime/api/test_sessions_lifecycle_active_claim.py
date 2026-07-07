"""Session lifecycle tests: no-flags ``end_session`` auto-release.

The no-flags ``end_session`` branch previously rejected sessions
holding active work-claims with ``ACTIVE_CLAIM``. The contract now
auto-releases each active claim with ``release_reason='session_ended'``
before ending the session. This file covers that default no-flags
behavior; ``test_sessions_lifecycle_release_claims.py`` covers the
``release_claims=True`` destructive-guard branch.
"""

from __future__ import annotations

import pytest
from unittest.mock import patch


from runtime.api.test_sessions import (
    _register,
    conn,  # noqa: F401  (Postgres-backed pytest fixture)
)
from yoke_core.domain.sessions import (
    EVENT_HARNESS_SESSION_END_RELEASED_CLAIMS,
    EVENT_HARNESS_SESSION_ENDED,
    SessionError,
    claim_work,
    end_session,
    update_chain_checkpoint,
)


PRIMARY_ITEM_ID = 9999
SECONDARY_ITEM_ID = 7777
PRIMARY_ITEM_REF = f"YOK-{PRIMARY_ITEM_ID}"
SECONDARY_ITEM_REF = f"YOK-{SECONDARY_ITEM_ID}"


def _active_claim_count(conn, session_id: str) -> int:
    return conn.execute(
        "SELECT COUNT(*) AS cnt FROM work_claims "
        "WHERE session_id = %s AND released_at IS NULL",
        (session_id,),
    ).fetchone()["cnt"]


class TestNoFlagsAutoRelease:
    """end_session (no flags) auto-releases active claims before ending."""

    def test_ac1_no_flags_releases_active_claim_and_ends(self, conn):
        """AC-1: no-flags end_session auto-releases active claims and ends."""
        _register(conn)
        claim_work(conn, session_id="sess-1", item_id=PRIMARY_ITEM_REF)

        result = end_session(conn, "sess-1")

        # Session is ended
        assert result["ended_at"] is not None
        # Claim is released
        assert _active_claim_count(conn, "sess-1") == 0
        # Release reason recorded
        reason_row = conn.execute(
            "SELECT release_reason FROM work_claims WHERE session_id='sess-1'"
        ).fetchone()
        assert reason_row["release_reason"] == "session_ended"
        # released_claims payload surfaces on the response
        assert "released_claims" in result
        assert len(result["released_claims"]) == 1
        entry = result["released_claims"][0]
        assert entry["target_kind"] == "item"
        assert entry["item_id"] == PRIMARY_ITEM_ID
        assert "claim_id" in entry

    def test_ac2_no_claims_path_unchanged(self, conn):
        """AC-2: end_session with no claims still succeeds with no released_claims field."""
        _register(conn)
        result = end_session(conn, "sess-1")
        assert result["ended_at"] is not None
        assert "released_claims" not in result

    def test_force_does_not_change_no_flags_behavior(self, conn):
        """force=True still auto-releases (no longer a guard-bypass primitive)."""
        _register(conn)
        claim_work(conn, session_id="sess-1", item_id=PRIMARY_ITEM_REF)

        result = end_session(conn, "sess-1", force=True)

        assert result["ended_at"] is not None
        assert _active_claim_count(conn, "sess-1") == 0
        assert len(result["released_claims"]) == 1

    def test_ac3_chain_pending_still_blocks_no_flags(self, conn):
        """AC-3: CHAIN_PENDING guard still fires before the auto-release path."""
        _register(conn, session_id="sess-cp")
        update_chain_checkpoint(
            conn, "sess-cp",
            step=1, action="charge", chainable=True,
            handler_outcome="completed",
        )
        with pytest.raises(SessionError) as exc_info:
            end_session(conn, "sess-cp", force=True)
        assert exc_info.value.code == "CHAIN_PENDING"

        # Override clears it.
        result = end_session(
            conn,
            "sess-cp",
            override_chain_end=True,
            chain_end_rationale="harness restart — chain budget intentionally abandoned",
        )
        assert result["ended_at"] is not None

    @patch("yoke_core.domain.sessions_analytics._emit_session_event")
    def test_no_flags_emits_released_claims_event(self, mock_emit, conn):
        """No-flags auto-release emits HarnessSessionEndReleasedClaims with via=no_flags."""
        _register(conn)
        claim_work(conn, session_id="sess-1", item_id=PRIMARY_ITEM_REF)
        mock_emit.reset_mock()

        end_session(conn, "sess-1")

        release_events = [
            c for c in mock_emit.call_args_list
            if c[0][0] == EVENT_HARNESS_SESSION_END_RELEASED_CLAIMS
        ]
        assert len(release_events) == 1
        ctx = release_events[0][1]["context"]
        assert ctx["released_count"] == 1
        assert ctx["release_reason"] == "session_ended"
        assert ctx["via"] == "no_flags"
        assert ctx["released_claims"][0]["item_id"] == PRIMARY_ITEM_ID

        ended_events = [
            c for c in mock_emit.call_args_list
            if c[0][0] == EVENT_HARNESS_SESSION_ENDED
        ]
        assert len(ended_events) == 1
        ended_ctx = ended_events[0][1]["context"]
        assert ended_ctx["released_claims_count"] == 1

    def test_ac12_multiple_claims_all_released(self, conn):
        """AC-12: multiple claims (item targets) all release on no-flags end."""
        _register(conn)
        claim_work(conn, session_id="sess-1", item_id=PRIMARY_ITEM_REF)
        claim_work(conn, session_id="sess-1", item_id=SECONDARY_ITEM_REF)

        result = end_session(conn, "sess-1")

        assert result["ended_at"] is not None
        assert _active_claim_count(conn, "sess-1") == 0
        assert len(result["released_claims"]) == 2
        item_ids = {entry["item_id"] for entry in result["released_claims"]}
        assert item_ids == {PRIMARY_ITEM_ID, SECONDARY_ITEM_ID}

    def test_historical_incident_regression(self, conn):
        """AC-1 follow-up: every claimed session ends cleanly on the no-flags branch.

        Six sessions each hold one claim. With the new contract, each
        end_session call succeeds, releases the claim, and leaves the
        session ended.
        """
        for i in range(6):
            sid = f"ghost-{i}"
            _register(conn, session_id=sid)
            claim_work(conn, session_id=sid, item_id=f"YOK-{100 + i}")

        for i in range(6):
            sid = f"ghost-{i}"
            result = end_session(conn, sid)
            assert result["ended_at"] is not None
            assert len(result["released_claims"]) == 1

        # No active claims remain
        active = conn.execute(
            "SELECT COUNT(*) as cnt FROM work_claims WHERE released_at IS NULL"
        ).fetchone()
        assert active["cnt"] == 0
