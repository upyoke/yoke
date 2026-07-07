"""Reclaim and race-safety tests for session_offer_with_ownership.

Split from ``test_sessions_queries.py``. Covers stale-claim reclaim,
ended-session reclaim, race-safe single-owner enforcement, manifest
capability resolution, and offer envelope persistence.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone

from runtime.api.test_sessions import (
    _ensure_active_session,  # plain helper
)
from runtime.api.sessions_api_stale_test_helpers import (
    conn,  # noqa: F401 — backend-aware fixture import
    ownership_conn,  # noqa: F401 — backend-aware fixture import
)
from yoke_core.domain.sessions import (
    session_offer_with_ownership,
)
from yoke_core.domain.sessions_queries import resolve_harness_capabilities


class TestSessionOfferReclaim:
    """Reclaim, race, and capability tests for session_offer_with_ownership."""

    def test_surface_specific_executor_uses_shared_registry(self, ownership_conn):
        """surface executors inherit shared registry truth through coarse manifest."""
        _conn, ws = ownership_conn
        manifest_dir = os.path.join(ws, "runtime", "harness", "codex")
        os.makedirs(manifest_dir, exist_ok=True)
        with open(os.path.join(manifest_dir, "manifest.json"), "w", encoding="utf-8") as handle:
            json.dump({"supports": {"command_source": "shared_yoke_registry"}}, handle)

        result = resolve_harness_capabilities("codex-desktop", ws)

        assert result["manifest_executor"] == "codex"
        assert result["source"] == "shared_registry"
        assert result["downstream_paths"] == ["shepherd", "refine", "advance", "polish", "usher"]

    def test_offer_envelope_includes_supported_paths(self, ownership_conn):
        """AC-6: offer envelope persisted in DB includes supported_paths."""
        conn, ws = ownership_conn
        _ensure_active_session(conn, "sess-envelope-1", ws, model="opus")
        session_offer_with_ownership(
            conn,
            session_id="sess-envelope-1",
            executor="DARIUS",
            provider="anthropic",
            model="opus",
            workspace=ws,
            supported_paths=["conduct"],
        )
        row = conn.execute(
            "SELECT offer_envelope FROM harness_sessions WHERE session_id = 'sess-envelope-1'"
        ).fetchone()
        assert row is not None
        envelope = json.loads(row["offer_envelope"])
        assert envelope["supported_paths"] == ["conduct"]

    def test_offer_reclaims_stale_heartbeat_claim(self, ownership_conn):
        """AC-2/AC-6: session_offer_with_ownership auto-reclaims
        a stale exclusive claim from a heartbeat-stale session and then
        acquires the item for the offering session."""
        conn, ws = ownership_conn
        _ensure_active_session(conn, "new-sess-reclaim", ws, model="opus")
        stale_iso = (datetime.now(timezone.utc) - timedelta(minutes=30)).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        )
        # Create a stale session holding item 100
        conn.execute(
            """INSERT INTO harness_sessions
               (session_id, executor, provider, model, workspace, offered_at, last_heartbeat)
               VALUES ('stale-sess', 'DARIUS', 'anthropic', 'claude', '/tmp', %s, %s)""",
            (stale_iso, stale_iso),
        )
        conn.execute(
            """INSERT INTO work_claims
               (session_id, target_kind, item_id, claim_type, claimed_at, last_heartbeat)
               VALUES ('stale-sess', 'item', 100, 'exclusive', %s, %s)""",
            (stale_iso, stale_iso),
        )
        conn.commit()

        result = session_offer_with_ownership(
            conn,
            session_id="new-sess-reclaim",
            executor="DARIUS",
            provider="anthropic",
            model="opus",
            workspace=ws,
        )

        # The offering session should acquire the item
        assert result["action_hint"] == "charge"
        assert result["new_claim"] is not None
        assert result["new_claim"]["item_id"] == 100

        # The stale claim should be released
        stale_claim = conn.execute(
            """SELECT released_at, release_reason FROM work_claims
               WHERE session_id = 'stale-sess' AND target_kind='item' AND item_id = 100"""
        ).fetchone()
        assert stale_claim["released_at"] is not None
        assert stale_claim["release_reason"] == "reclaimed"

    def test_offer_reclaims_ended_session_claim(self, ownership_conn):
        """AC-2/AC-6: session_offer_with_ownership auto-reclaims
        an unreleased claim from an already-ended session."""
        conn, ws = ownership_conn
        _ensure_active_session(conn, "new-sess-ended", ws, model="opus")
        ended_iso = (datetime.now(timezone.utc) - timedelta(minutes=5)).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        )
        # Create an ended session with an unreleased claim
        conn.execute(
            """INSERT INTO harness_sessions
               (session_id, executor, provider, model, workspace, offered_at, last_heartbeat, ended_at)
               VALUES ('ended-sess', 'DARIUS', 'anthropic', 'claude', '/tmp', %s, %s, %s)""",
            (ended_iso, ended_iso, ended_iso),
        )
        conn.execute(
            """INSERT INTO work_claims
               (session_id, target_kind, item_id, claim_type, claimed_at, last_heartbeat)
               VALUES ('ended-sess', 'item', 100, 'exclusive', %s, %s)""",
            (ended_iso, ended_iso),
        )
        conn.commit()

        result = session_offer_with_ownership(
            conn,
            session_id="new-sess-ended",
            executor="DARIUS",
            provider="anthropic",
            model="opus",
            workspace=ws,
        )

        assert result["action_hint"] == "charge"
        assert result["new_claim"] is not None
        assert result["new_claim"]["item_id"] == 100

    def test_offer_only_stale_work_returns_charge(self, ownership_conn):
        """AC-3: if only stale-claimed work exists on the frontier,
        the offer surface recovers it instead of returning no_work."""
        conn, ws = ownership_conn
        _ensure_active_session(conn, "rescuer-sess", ws, model="opus")
        stale_iso = (datetime.now(timezone.utc) - timedelta(minutes=30)).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        )
        # Stale session claims the only runnable item
        conn.execute(
            """INSERT INTO harness_sessions
               (session_id, executor, provider, model, workspace, offered_at, last_heartbeat)
               VALUES ('sole-stale', 'DARIUS', 'anthropic', 'claude', '/tmp', %s, %s)""",
            (stale_iso, stale_iso),
        )
        conn.execute(
            """INSERT INTO work_claims
               (session_id, target_kind, item_id, claim_type, claimed_at, last_heartbeat)
               VALUES ('sole-stale', 'item', 100, 'exclusive', %s, %s)""",
            (stale_iso, stale_iso),
        )
        conn.commit()

        result = session_offer_with_ownership(
            conn,
            session_id="rescuer-sess",
            executor="DARIUS",
            provider="anthropic",
            model="opus",
            workspace=ws,
        )

        # Must NOT return no_work -- must recover the stale item
        assert result["action_hint"] == "charge"
        assert result["new_claim"] is not None

    def test_offer_race_safe_no_duplicate_claims(self, ownership_conn):
        """AC-5: if a live session holds the claim, reclaim does
        not release it, preserving single-owner safety."""
        conn, ws = ownership_conn
        _ensure_active_session(conn, "competing-sess", ws, model="opus")
        fresh_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        # Create a live session with a fresh claim on item 100
        conn.execute(
            """INSERT INTO harness_sessions
               (session_id, executor, provider, model, workspace, offered_at, last_heartbeat)
               VALUES ('live-sess', 'DARIUS', 'anthropic', 'claude', '/tmp', %s, %s)""",
            (fresh_iso, fresh_iso),
        )
        conn.execute(
            """INSERT INTO work_claims
               (session_id, target_kind, item_id, claim_type, claimed_at, last_heartbeat)
               VALUES ('live-sess', 'item', 100, 'exclusive', %s, %s)""",
            (fresh_iso, fresh_iso),
        )
        conn.commit()

        result = session_offer_with_ownership(
            conn,
            session_id="competing-sess",
            executor="DARIUS",
            provider="anthropic",
            model="opus",
            workspace=ws,
        )

        # The live claim is NOT reclaimed -- competing session gets no_work
        assert result["action_hint"] == "no_work"
        # The live claim is still active
        live_claim = conn.execute(
            """SELECT released_at FROM work_claims
               WHERE session_id = 'live-sess' AND target_kind='item' AND item_id = 100"""
        ).fetchone()
        assert live_claim["released_at"] is None
