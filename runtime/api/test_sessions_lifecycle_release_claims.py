"""Session lifecycle tests: end_session(release_claims=True) branch.

Split from test_sessions_lifecycle_active_claim.py to keep authored
files under the 350-line cap. Covers the destructive claim-release
branch, the upstream CHAIN_PENDING gate, and the chain-override
propagation path.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from unittest.mock import patch


def _age_heartbeat(conn, session_id: str, seconds: int) -> None:
    """Backdate ``last_heartbeat`` on the session and its active claims.

    The destructive branch does not read heartbeats — this helper only
    feeds the stale-session reclaim sweep contract
    (``session_stale_ttl_minutes``). Tests that need chain-gate behavior
    should set up the chain checkpoint directly via
    ``update_chain_checkpoint``.
    """
    ts = (datetime.now(timezone.utc) - timedelta(seconds=seconds)).isoformat(
        timespec="microseconds"
    ).replace("+00:00", "Z")
    conn.execute(
        "UPDATE harness_sessions SET last_heartbeat = %s WHERE session_id = %s",
        (ts, session_id),
    )
    conn.execute(
        "UPDATE work_claims SET last_heartbeat = %s, claimed_at = %s "
        "WHERE session_id = %s AND released_at IS NULL",
        (ts, ts, session_id),
    )
    conn.commit()


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


class TestSessionEndReleaseClaims:
    """SessionEnd hook auto-releases claims when release_claims=True."""

    @patch("yoke_core.domain.sessions_analytics._emit_session_event")
    def test_release_claims_true_releases_and_ends(self, mock_emit, conn):
        """With release_claims=True and no chain pending, claims release and session ends."""
        _register(conn)
        claim_work(conn, session_id="sess-1", item_id=PRIMARY_ITEM_REF)
        mock_emit.reset_mock()

        result = end_session(conn, "sess-1", force=True, release_claims=True)

        # Session ended
        assert result["ended_at"] is not None
        # Claims released
        active = conn.execute(
            "SELECT COUNT(*) as cnt FROM work_claims "
            "WHERE session_id='sess-1' AND released_at IS NULL"
        ).fetchone()
        assert active["cnt"] == 0
        # Release reason recorded
        reason = conn.execute(
            "SELECT release_reason FROM work_claims WHERE session_id='sess-1'"
        ).fetchone()
        assert reason["release_reason"] == "session_ended"
        # HarnessSessionEndReleasedClaims event emitted
        release_events = [
            c for c in mock_emit.call_args_list
            if c[0][0] == EVENT_HARNESS_SESSION_END_RELEASED_CLAIMS
        ]
        assert len(release_events) == 1
        ctx = release_events[0][1]["context"]
        assert ctx["released_count"] == 1
        assert len(ctx["claim_details"]) == 1
        # HarnessSessionEnded event also emitted
        ended_events = [
            c for c in mock_emit.call_args_list
            if c[0][0] == EVENT_HARNESS_SESSION_ENDED
        ]
        assert len(ended_events) == 1

    def test_release_claims_false_auto_releases_via_no_flags_branch(self, conn):
        """release_claims=False (no-flags) now auto-releases via the typed path.

        The contract previously raised ACTIVE_CLAIM here; explicit
        no-flags session-end now auto-releases with
        ``release_reason='session_ended'``. The destructive-guard
        branch covered in this file remains the ``release_claims=True``
        contract.
        """
        _register(conn)
        claim_work(conn, session_id="sess-1", item_id=PRIMARY_ITEM_REF)

        result = end_session(conn, "sess-1", force=True, release_claims=False)

        # Session ended; claim released through the no-flags helper
        assert result["ended_at"] is not None
        active = conn.execute(
            "SELECT COUNT(*) as cnt FROM work_claims "
            "WHERE session_id='sess-1' AND released_at IS NULL"
        ).fetchone()
        assert active["cnt"] == 0
        assert result["released_claims"][0]["item_id"] == PRIMARY_ITEM_ID

    @patch("yoke_core.domain.sessions_analytics._emit_session_event")
    def test_release_claims_no_claims_noop(self, mock_emit, conn):
        """With release_claims=True but no claims, session ends normally."""
        _register(conn)
        mock_emit.reset_mock()

        result = end_session(conn, "sess-1", force=True, release_claims=True)
        assert result["ended_at"] is not None

        # No release event emitted
        release_events = [
            c for c in mock_emit.call_args_list
            if c[0][0] == EVENT_HARNESS_SESSION_END_RELEASED_CLAIMS
        ]
        assert len(release_events) == 0

    def test_release_claims_with_chain_pending_raises_chain_pending(self, conn):
        """A pending chain checkpoint blocks SessionEnd at the chain gate.

        ``end_session`` rejects with ``CHAIN_PENDING`` before reaching the
        destructive guard whenever a chainable checkpoint has budget and
        no operator override is supplied. The session row and claim row
        remain untouched.
        """
        _register(conn)
        claim_work(conn, session_id="sess-1", item_id=PRIMARY_ITEM_REF)
        update_chain_checkpoint(
            conn, "sess-1",
            step=1, action="charge", chainable=True,
            handler_outcome="completed",
        )
        with pytest.raises(SessionError) as exc_info:
            end_session(conn, "sess-1", force=True, release_claims=True)
        assert exc_info.value.code == "CHAIN_PENDING"
        row = conn.execute(
            "SELECT ended_at FROM harness_sessions WHERE session_id='sess-1'"
        ).fetchone()
        assert row["ended_at"] is None
        active = conn.execute(
            "SELECT COUNT(*) as cnt FROM work_claims "
            "WHERE session_id='sess-1' AND released_at IS NULL"
        ).fetchone()
        assert active["cnt"] == 1

    @patch("yoke_core.domain.sessions_analytics._emit_session_event")
    def test_release_claims_multiple_claims(self, mock_emit, conn):
        """Multiple claims (item + epic_task) are all released.

        Replaces the legacy item+sentinel pattern: STRATEGIZE/FEED are
        process targets reached through the typed API, not item ids.
        Use a second item-target claim instead — the multi-claim release
        path is target-kind-agnostic.
        """
        _register(conn)
        claim_work(conn, session_id="sess-1", item_id=PRIMARY_ITEM_REF)
        claim_work(conn, session_id="sess-1", item_id=SECONDARY_ITEM_REF)
        mock_emit.reset_mock()

        result = end_session(conn, "sess-1", force=True, release_claims=True)
        assert result["ended_at"] is not None

        active = conn.execute(
            "SELECT COUNT(*) as cnt FROM work_claims "
            "WHERE session_id='sess-1' AND released_at IS NULL"
        ).fetchone()
        assert active["cnt"] == 0

        release_events = [
            c for c in mock_emit.call_args_list
            if c[0][0] == EVENT_HARNESS_SESSION_END_RELEASED_CLAIMS
        ]
        assert len(release_events) == 1
        ctx = release_events[0][1]["context"]
        assert ctx["released_count"] == 2
        assert len(ctx["claim_details"]) == 2

    @patch("yoke_core.domain.sessions_analytics._emit_session_event")
    def test_release_claims_chain_override_authorized_ends(self, mock_emit, conn):
        """override_chain_end+rationale ends the session even with active claim and pending chain.

        Without the override, the CHAIN_PENDING gate refuses and the
        claim stays active. With the override, the chain budget is
        treated as waived: claims release, the session ends, and
        HarnessSessionEnded carries chain_override_authorized in
        agent_presence_evidence.
        """
        _register(conn)
        claim_work(conn, session_id="sess-1", item_id=PRIMARY_ITEM_REF)
        update_chain_checkpoint(
            conn, "sess-1",
            step=1, action="charge", chainable=True,
            handler_outcome="completed",
        )
        mock_emit.reset_mock()

        result = end_session(
            conn,
            "sess-1",
            force=True,
            release_claims=True,
            override_chain_end=True,
            chain_end_rationale="operator: stale session, ending per request",
        )

        assert result["ended_at"] is not None
        active = conn.execute(
            "SELECT COUNT(*) as cnt FROM work_claims "
            "WHERE session_id='sess-1' AND released_at IS NULL"
        ).fetchone()
        assert active["cnt"] == 0

        release_events = [
            c for c in mock_emit.call_args_list
            if c[0][0] == EVENT_HARNESS_SESSION_END_RELEASED_CLAIMS
        ]
        assert len(release_events) == 1
        release_ctx = release_events[0][1]["context"]
        assert release_ctx["agent_presence_evidence"]["chain_override_authorized"] is True

        ended_events = [
            c for c in mock_emit.call_args_list
            if c[0][0] == EVENT_HARNESS_SESSION_ENDED
        ]
        assert len(ended_events) == 1
        ended_ctx = ended_events[0][1]["context"]
        assert ended_ctx["chain_override_authorized"] is True
        assert ended_ctx["chain_end_rationale"] == (
            "operator: stale session, ending per request"
        )
        assert (
            ended_ctx["agent_presence_evidence"]["chain_override_authorized"] is True
        )
