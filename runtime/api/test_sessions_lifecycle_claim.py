"""Claim acquisition, release, and handoff-boundary tests for harness sessions."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest


_STALE_TS_60 = (datetime.now(timezone.utc) - timedelta(minutes=60)).strftime(
    "%Y-%m-%dT%H:%M:%SZ"
)

from runtime.api.test_sessions import (
    _apply_on_backend,
    _create_schema,
    _register,
    conn,  # noqa: F401  (pytest fixture)
)
from runtime.api.fixtures.file_test_db import connect_test_db, init_test_db
from runtime.api.sessions_api_stale_test_helpers import (
    EVENTS_TABLE_FOR_STALE_DETECTION,
    apply_ddl_statements,
)
from yoke_core.domain.sessions import (
    SessionError,
    claim_work,
    end_session,
    get_claim_for_work_unit,
    list_claims_for_session,
    release_all_claims,
    release_claim,
)


# ---------------------------------------------------------------------------
# Claim acquisition tests
# ---------------------------------------------------------------------------


class TestClaimWork:
    def test_claim_item_succeeds(self, conn):
        _register(conn)
        result = claim_work(conn, session_id="sess-1", item_id="YOK-9999")
        assert result["session_id"] == "sess-1"
        assert result["item_id"] == 9999
        assert result["target_kind"] == "item"
        assert result["claim_type"] == "exclusive"
        assert result["released_at"] is None

    def test_claim_numeric_item_is_normalized(self, conn):
        _register(conn)
        result = claim_work(conn, session_id="sess-1", item_id="09999")
        assert result["item_id"] == 9999

    def test_claim_sets_current_item_attribution(self, conn):
        _register(conn)
        claim_work(conn, session_id="sess-1", item_id="YOK-9999")
        row = conn.execute(
            "SELECT current_item_id, recent_item_id FROM harness_sessions WHERE session_id = 'sess-1'"
        ).fetchone()
        assert row["current_item_id"] == "9999"
        assert row["recent_item_id"] is None

    def test_claim_sentinel_item_is_rejected(self, conn):
        """STRATEGIZE/FEED/DOCTOR are no longer valid item_ids — they are
        process targets reached through claim_work(target=make_process_target(...))."""
        _register(conn)
        with pytest.raises((ValueError, TypeError)):
            claim_work(conn, session_id="sess-1", item_id="STRATEGIZE")

    def test_claim_requires_item_id(self, conn):
        """claim_work requires item_id (no epic_id/task_num)."""
        _register(conn)
        with pytest.raises(SessionError) as exc_info:
            claim_work(conn, session_id="sess-1")
        assert exc_info.value.code == "INVALID_CLAIM"

    def test_claim_exclusive_conflict_rejected(self, conn):
        _register(conn, session_id="sess-1")
        _register(conn, session_id="sess-2")
        claim_work(conn, session_id="sess-1", item_id="YOK-9999")
        with pytest.raises(SessionError) as exc_info:
            claim_work(conn, session_id="sess-2", item_id="YOK-9999")
        assert exc_info.value.code == "ALREADY_CLAIMED"

    def test_claim_auto_reaps_stale_session_on_conflict(self, conn):
        """claim_work runs clean_stale_harness_sessions on conflict
        and succeeds if the conflicting session was stale."""
        # Need events table for the stale-session reaper. Mirrors production
        # via the shared helper — cleanup queries read events.session_id as
        # an indexed column, so the test fixture must carry that column.
        apply_ddl_statements(conn, EVENTS_TABLE_FOR_STALE_DETECTION)
        _register(conn, session_id="sess-stale")
        _register(conn, session_id="sess-new")
        claim_work(conn, session_id="sess-stale", item_id="YOK-99")
        # Make the stale session's heartbeat old enough to be reaped
        conn.execute(
            "UPDATE harness_sessions SET last_heartbeat = %s "
            "WHERE session_id = 'sess-stale'",
            (_STALE_TS_60,),
        )
        conn.execute(
            "UPDATE work_claims SET claimed_at = %s, last_heartbeat = %s "
            "WHERE session_id = 'sess-stale'",
            (_STALE_TS_60, _STALE_TS_60),
        )
        # This should auto-reap sess-stale and succeed
        result = claim_work(conn, session_id="sess-new", item_id="YOK-99")
        assert result["session_id"] == "sess-new"
        assert result["item_id"] == 99
        # Verify the stale session's claim was released
        stale_claim = conn.execute(
            "SELECT released_at, release_reason FROM work_claims "
            "WHERE session_id = 'sess-stale'"
        ).fetchone()
        assert stale_claim["released_at"] is not None

    def test_claim_by_same_session_is_idempotent(self, conn):
        """Same-session re-claim returns the existing row instead of raising.

        Aligns with the harness-CLI cmd_claim idempotent contract: agents that
        re-run claim during long workflows should not see DUPLICATE_CLAIM.
        """
        _register(conn)
        first = claim_work(conn, session_id="sess-1", item_id="YOK-9999")
        second = claim_work(conn, session_id="sess-1", item_id="YOK-9999")
        assert second["id"] == first["id"]
        assert second["released_at"] is None

    def test_claim_ended_session_fails(self, conn):
        _register(conn)
        end_session(conn, "sess-1")
        with pytest.raises(SessionError) as exc_info:
            claim_work(conn, session_id="sess-1", item_id="YOK-9999")
        assert exc_info.value.code == "SESSION_ENDED"

    def test_claim_nonexistent_session_fails(self, conn):
        with pytest.raises(SessionError) as exc_info:
            claim_work(conn, session_id="ghost", item_id="YOK-9999")
        assert exc_info.value.code == "NOT_FOUND"

    def test_claim_after_release_succeeds(self, conn):
        _register(conn, session_id="sess-1")
        _register(conn, session_id="sess-2")
        c = claim_work(conn, session_id="sess-1", item_id="YOK-9999")
        release_claim(conn, c["id"], reason="completed")
        result = claim_work(conn, session_id="sess-2", item_id="YOK-9999")
        assert result["session_id"] == "sess-2"

    def test_end_session_moves_current_item_to_recent(self, conn):
        _register(conn)
        c = claim_work(conn, session_id="sess-1", item_id="YOK-9999")
        release_claim(conn, c["id"], reason="completed")
        end_session(conn, "sess-1")
        row = conn.execute(
            "SELECT current_item_id, recent_item_id FROM harness_sessions WHERE session_id = 'sess-1'"
        ).fetchone()
        assert row["current_item_id"] is None
        assert row["recent_item_id"] == "9999"

    def test_claim_race_after_prechecks_is_rejected(self, tmp_path):
        """A late conflicting claim must still be rejected without double-assigning.

        Ported off the SQLite Connection subclass: ``_RaceConn`` wraps the facade
        and commits a competing claim from a second connection just before the
        first INSERT, so the gated ``WHERE NOT EXISTS`` inserts zero rows.
        """
        class _RaceConn:
            def __init__(self, inner, db_path):
                self._inner, self._db_path, self._injected = inner, db_path, False

            def execute(self, sql, params=()):
                if not self._injected and " ".join(sql.split()).startswith("INSERT INTO work_claims"):
                    self._injected = True
                    side = connect_test_db(self._db_path)
                    try:
                        side.execute(
                            "INSERT INTO work_claims (session_id, target_kind, item_id, "
                            "claim_type, claimed_at, last_heartbeat) "
                            "VALUES (%s, 'item', %s, 'exclusive', %s, %s)",
                            ("sess-2", 9999, "2026-04-03T00:00:00Z", "2026-04-03T00:00:00Z"),
                        )
                        side.commit()
                    finally:
                        side.close()
                return self._inner.execute(sql, params)

            def __getattr__(self, name):
                return getattr(self._inner, name)

        with init_test_db(tmp_path, apply_schema=lambda: _apply_on_backend(_create_schema)):
            db_path = str(tmp_path / "claim-race.db")
            seed = connect_test_db(db_path)
            _register(seed, session_id="sess-1")
            _register(seed, session_id="sess-2")
            seed.close()

            conn = _RaceConn(connect_test_db(db_path), db_path)
            try:
                with pytest.raises(SessionError) as exc_info:
                    claim_work(conn, session_id="sess-1", item_id="YOK-9999")
                assert exc_info.value.code == "ALREADY_CLAIMED"
                claim = get_claim_for_work_unit(conn, item_id="YOK-9999")
                assert claim is not None
                assert claim["session_id"] == "sess-2"
            finally:
                conn.close()

    def test_claim_invalid_spec_fails(self, conn):
        _register(conn)
        with pytest.raises(SessionError) as exc_info:
            claim_work(conn, session_id="sess-1")
        assert exc_info.value.code == "INVALID_CLAIM"


# ---------------------------------------------------------------------------
# Claim release tests
# ---------------------------------------------------------------------------


class TestClaimRelease:
    def test_release_sets_released_at_and_reason(self, conn):
        _register(conn)
        c = claim_work(conn, session_id="sess-1", item_id="YOK-9999")
        result = release_claim(conn, c["id"], reason="completed")
        assert result["released_at"] is not None
        assert result["release_reason"] == "completed"

    def test_release_already_released_fails(self, conn):
        _register(conn)
        c = claim_work(conn, session_id="sess-1", item_id="YOK-9999")
        release_claim(conn, c["id"])
        with pytest.raises(SessionError) as exc_info:
            release_claim(conn, c["id"])
        assert exc_info.value.code == "ALREADY_RELEASED"

    def test_release_nonexistent_claim_fails(self, conn):
        with pytest.raises(SessionError) as exc_info:
            release_claim(conn, 99999)
        assert exc_info.value.code == "NOT_FOUND"

    def test_release_all_releases_multiple(self, conn):
        _register(conn)
        claim_work(conn, session_id="sess-1", item_id="YOK-1")
        claim_work(conn, session_id="sess-1", item_id="YOK-2")
        count = release_all_claims(conn, "sess-1", reason="released")
        assert count == 2
        claims = list_claims_for_session(conn, "sess-1", active_only=True)
        assert len(claims) == 0

    def test_end_session_auto_releases_active_claims(self, conn):
        """No-flags end_session now auto-releases active claims and ends.

        Contract change: the prior ACTIVE_CLAIM rejection has been
        replaced by an auto-release through the typed work-claim
        release path with ``release_reason='session_ended'``. The
        success response carries the per-claim release payload.
        """
        _register(conn)
        claim_work(conn, session_id="sess-1", item_id="YOK-1")
        claim_work(conn, session_id="sess-1", item_id="YOK-2")
        result = end_session(conn, "sess-1")
        assert result["ended_at"] is not None
        active = conn.execute(
            "SELECT COUNT(*) as cnt FROM work_claims "
            "WHERE session_id='sess-1' AND released_at IS NULL"
        ).fetchone()
        assert active["cnt"] == 0
        assert len(result["released_claims"]) == 2

    def test_end_session_succeeds_after_claims_released(self, conn):
        """end_session works when all claims are pre-released."""
        _register(conn)
        c1 = claim_work(conn, session_id="sess-1", item_id="YOK-1")
        c2 = claim_work(conn, session_id="sess-1", item_id="YOK-2")
        release_claim(conn, c1["id"], reason="completed")
        release_claim(conn, c2["id"], reason="completed")
        result = end_session(conn, "sess-1")
        assert result["ended_at"] is not None


# ---------------------------------------------------------------------------
# Handoff claim boundary tests
# ---------------------------------------------------------------------------


class TestHandoffClaimBoundary:
    """Explicit handoffs remain hard command boundaries."""

    def test_handoff_release_leaves_no_active_claim(self, conn):
        """A handoff release no longer grants implicit same-session ownership."""
        _register(conn)
        c = claim_work(conn, session_id="sess-1", item_id="YOK-99")
        release_claim(conn, c["id"], reason="handed_off")

        active = get_claim_for_work_unit(conn, item_id="99")
        assert active is None

    def test_same_session_can_claim_again_explicitly_after_handoff(self, conn):
        """The downstream command can still claim the handed-off item explicitly."""
        _register(conn)
        c = claim_work(conn, session_id="sess-1", item_id="YOK-99")
        release_claim(conn, c["id"], reason="handed_off")

        new_claim = claim_work(conn, session_id="sess-1", item_id="YOK-99")
        assert new_claim["session_id"] == "sess-1"

    def test_different_session_can_claim_after_handoff(self, conn):
        """A new command/session may claim the item after the handoff release."""
        _register(conn, session_id="sess-1")
        _register(conn, session_id="sess-2")
        c = claim_work(conn, session_id="sess-1", item_id="YOK-99")
        release_claim(conn, c["id"], reason="handed_off")

        c2 = claim_work(conn, session_id="sess-2", item_id="YOK-99")
        assert c2["session_id"] == "sess-2"

    def test_completed_release_remains_terminal(self, conn):
        """Completed releases are not resumable without a fresh success path."""
        _register(conn)
        c = claim_work(conn, session_id="sess-1", item_id="YOK-99")
        release_claim(conn, c["id"], reason="completed")

        active = get_claim_for_work_unit(conn, item_id="99")
        assert active is None

    def test_standard_handoff_still_releases_correctly(self, conn):
        """AC-04: standard flow releases the claim, no auto-reacquire by
        a different session picking up polish."""
        from yoke_core.domain.sessions import release_item_claim_for_execution

        _register(conn)
        claim_work(conn, session_id="sess-1", item_id="YOK-99")
        result = release_item_claim_for_execution(
            conn, "sess-1", "YOK-99", "handoff-to-polish"
        )
        assert result["released"] is True

        # Claim is now released
        active = get_claim_for_work_unit(conn, item_id="99")
        assert active is None

        # A different session can now claim it
        _register(conn, session_id="sess-2")
        c2 = claim_work(conn, session_id="sess-2", item_id="YOK-99")
        assert c2["session_id"] == "sess-2"
