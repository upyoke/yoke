"""Session query tests: list, get, query surface, basic offer/ownership.

Sibling modules cover related surfaces:

- ``test_sessions_queries_lanes.py`` — lane filtering and supported_paths.
- ``test_sessions_queries_reclaim.py`` — stale/ended-session reclaim, race safety.
- ``test_sessions_queries_telemetry.py`` — Codex runtime ID and post-decision telemetry.
"""

from __future__ import annotations

from unittest.mock import patch

from runtime.api.test_sessions import (
    _register,
    conn,
    ownership_conn,
    _ensure_active_session,
)
from yoke_core.domain.sessions import (
    claim_work,
    end_session,
    get_claim_for_work_unit,
    list_harness_sessions,
    list_claims_for_session,
    release_claim,
    session_offer_with_ownership,
    set_session_mode,
)
from runtime.api.test_constants import TEST_MODEL_ID


# ---------------------------------------------------------------------------
# Query surface tests
# ---------------------------------------------------------------------------


class TestQuerySurface:
    def test_list_harness_sessions(self, conn):
        _register(conn, session_id="sess-1")
        _register(conn, session_id="sess-2", execution_lane="review")
        harness_sessions = list_harness_sessions(conn)
        assert len(harness_sessions) == 2

    def test_list_harness_sessions_filter_lane(self, conn):
        _register(conn, session_id="sess-1", execution_lane="primary")
        _register(conn, session_id="sess-2", execution_lane="review")
        harness_sessions = list_harness_sessions(conn, lane="review")
        assert len(harness_sessions) == 1
        assert harness_sessions[0]["session_id"] == "sess-2"

    def test_list_harness_sessions_filter_mode(self, conn):
        _register(conn, session_id="sess-1", mode="charge")
        _register(conn, session_id="sess-2", mode="wait")
        harness_sessions = list_harness_sessions(conn, mode="charge")
        assert len(harness_sessions) == 1

    def test_list_harness_sessions_excludes_ended(self, conn):
        _register(conn, session_id="sess-1")
        _register(conn, session_id="sess-2")
        end_session(conn, "sess-2")
        harness_sessions = list_harness_sessions(conn)
        assert len(harness_sessions) == 1

    def test_list_claims_for_session(self, conn):
        _register(conn)
        claim_work(conn, session_id="sess-1", item_id="YOK-1")
        claim_work(conn, session_id="sess-1", item_id="YOK-2")
        claims = list_claims_for_session(conn, "sess-1")
        assert len(claims) == 2

    def test_list_claims_active_only(self, conn):
        _register(conn)
        c = claim_work(conn, session_id="sess-1", item_id="YOK-1")
        claim_work(conn, session_id="sess-1", item_id="YOK-2")
        release_claim(conn, c["id"])
        active = list_claims_for_session(conn, "sess-1", active_only=True)
        all_claims = list_claims_for_session(conn, "sess-1", active_only=False)
        assert len(active) == 1
        assert len(all_claims) == 2

    def test_get_claim_for_item(self, conn):
        _register(conn)
        claim_work(conn, session_id="sess-1", item_id="YOK-9999")
        result = get_claim_for_work_unit(conn, item_id="YOK-9999")
        assert result is not None
        assert result["session_id"] == "sess-1"

    def test_get_claim_for_epic_parent_item(self, conn):
        """epic task ownership uses parent item claim."""
        _register(conn)
        claim_work(conn, session_id="sess-1", item_id="YOK-100")
        result = get_claim_for_work_unit(conn, item_id="YOK-100")
        assert result is not None
        assert result["session_id"] == "sess-1"

    def test_get_claim_for_unclaimed_item(self, conn):
        result = get_claim_for_work_unit(conn, item_id="YOK-99")
        assert result is None

    def test_get_claim_returns_none_for_no_spec(self, conn):
        result = get_claim_for_work_unit(conn)
        assert result is None

    def test_set_session_mode_updates_session(self, conn):
        _register(conn)
        result = set_session_mode(conn, "sess-1", "charge")
        assert result["mode"] == "charge"

        row = conn.execute(
            "SELECT mode FROM harness_sessions WHERE session_id='sess-1'"
        ).fetchone()
        assert row["mode"] == "charge"


# ---------------------------------------------------------------------------
# Basic ownership-helper tests (basics + contract). Lane/reclaim/telemetry
# tests live in sibling files (see header docstring).
# ---------------------------------------------------------------------------


class TestSessionOfferWithOwnership:
    """Basic offer + heartbeat + claim contract for session_offer_with_ownership."""

    @patch("yoke_core.domain.sessions_analytics._emit_event")
    def test_session_offered_uses_session_offer_contract(self, mock_emit, ownership_conn):
        conn, ws = ownership_conn
        _ensure_active_session(conn, "sess-offer-contract", ws)
        session_offer_with_ownership(
            conn,
            session_id="sess-offer-contract",
            executor="DARIUS",
            provider="anthropic",
            model=TEST_MODEL_ID,
            workspace=ws,
            step=4,
            project_scope=["buzz"],
        )

        offer_args = None
        offer_kwargs = None
        for args, kwargs in mock_emit.call_args_list:
            if args and args[0] == "HarnessSessionOffered":
                offer_args = args
                offer_kwargs = kwargs
                break
        assert offer_args is not None
        assert offer_kwargs["event_kind"] == "system"
        assert offer_kwargs["event_type"] == "session_offer"
        assert offer_kwargs["source_type"] == "backend"
        assert offer_kwargs["project"] == "buzz"
        assert offer_kwargs["context"]["step"] == 4
        assert offer_kwargs["context"]["project_scope"] == ["buzz"]

    def test_offer_uses_existing_active_session(self, ownership_conn):
        """session-offer requires an already-active session."""
        conn, ws = ownership_conn
        _ensure_active_session(conn, "test-sess-1", ws)
        result = session_offer_with_ownership(
            conn,
            session_id="test-sess-1",
            executor="DARIUS",
            provider="anthropic",
            model=TEST_MODEL_ID,
            workspace=ws,
        )
        assert result["session"]["session_id"] == "test-sess-1"
        # Verify DB row exists
        row = conn.execute(
            "SELECT * FROM harness_sessions WHERE session_id = 'test-sess-1'"
        ).fetchone()
        assert row is not None
        assert row["ended_at"] is None

    def test_heartbeats_existing_session(self, ownership_conn):
        """AC-1: re-offer heartbeats existing session instead of failing."""
        conn, ws = ownership_conn
        _ensure_active_session(conn, "test-sess-hb", ws, model="opus")
        session_offer_with_ownership(
            conn, session_id="test-sess-hb", executor="DARIUS",
            provider="anthropic", model="opus", workspace=ws,
        )
        # Second offer with same session_id heartbeats (no error)
        result = session_offer_with_ownership(
            conn, session_id="test-sess-hb", executor="DARIUS",
            provider="anthropic", model="opus", workspace=ws,
        )
        # Should get resume since the first offer claimed the item
        assert result["session"]["session_id"] == "test-sess-hb"

    def test_charge_persists_exclusive_claim(self, ownership_conn):
        """AC-2: charge persists a work_claims row before returning."""
        conn, ws = ownership_conn
        _ensure_active_session(conn, "test-sess-claim", ws, model="opus")
        result = session_offer_with_ownership(
            conn, session_id="test-sess-claim", executor="DARIUS",
            provider="anthropic", model="opus", workspace=ws,
        )
        assert result["action_hint"] == "charge"
        assert result["new_claim"] is not None
        assert result["new_claim"]["item_id"] == 100
        # Verify claim exists in DB
        claim_row = conn.execute(
            "SELECT * FROM work_claims WHERE session_id = 'test-sess-claim' AND released_at IS NULL"
        ).fetchone()
        assert claim_row is not None
        assert claim_row["item_id"] == 100

    def test_concurrent_offers_no_double_assign(self, ownership_conn):
        """AC-3: two concurrent offers never both claim the same item."""
        conn, ws = ownership_conn
        _ensure_active_session(conn, "sess-A", ws, executor="A", model="opus")
        _ensure_active_session(conn, "sess-B", ws, executor="B", model="opus")
        # First session claims
        r1 = session_offer_with_ownership(
            conn, session_id="sess-A", executor="A",
            provider="anthropic", model="opus", workspace=ws,
        )
        assert r1["action_hint"] == "charge"
        assert r1["new_claim"]["item_id"] == 100

        # Second session with a different session_id should NOT get the same item
        r2 = session_offer_with_ownership(
            conn, session_id="sess-B", executor="B",
            provider="anthropic", model="opus", workspace=ws,
        )
        # No other runnable items, so no_work
        assert r2["action_hint"] == "no_work"
        assert r2["new_claim"] is None

    def test_resume_when_claim_exists(self, ownership_conn):
        """AC-4: re-offer with same session returns resume, not charge."""
        conn, ws = ownership_conn
        _ensure_active_session(conn, "sess-resume", ws, model="opus")
        r1 = session_offer_with_ownership(
            conn, session_id="sess-resume", executor="DARIUS",
            provider="anthropic", model="opus", workspace=ws,
        )
        assert r1["action_hint"] == "charge"

        # Second offer with same session_id sees existing claim
        r2 = session_offer_with_ownership(
            conn, session_id="sess-resume", executor="DARIUS",
            provider="anthropic", model="opus", workspace=ws,
        )
        assert r2["action_hint"] == "resume"
        assert len(r2["claims"]) > 0
        assert r2["claims"][0]["item_id"] == 100
