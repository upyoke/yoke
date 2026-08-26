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
    conn as conn,  # backend-aware fixture re-export
    ownership_conn as ownership_conn,  # backend-aware fixture re-export
)
from yoke_core.domain.sessions import (
    session_offer_with_ownership,
)
from yoke_core.domain.harness_capability_registry import shared_downstream_paths
from yoke_core.domain.sessions_queries import resolve_harness_capabilities
from yoke_core.domain.work_claim_targets import make_item_target


def _insert_item_claim(conn, session_id: str, item_id: int, claimed_at: str) -> None:
    target = make_item_target(item_id)
    conn.execute(
        "INSERT INTO work_claims "
        "(session_id, target_kind, scope, claim_type, claimed_at, last_heartbeat) "
        "VALUES (%s, %s, %s, 'exclusive', %s, %s)",
        (session_id, target.kind, target.scope_json(), claimed_at, claimed_at),
    )


def _claim_row(conn, session_id: str, item_id: int):
    target = make_item_target(item_id)
    return conn.execute(
        "SELECT released_at, release_reason FROM work_claims "
        "WHERE session_id = %s AND target_kind = %s AND scope = %s",
        (session_id, target.kind, target.scope_json()),
    ).fetchone()


class TestSessionOfferReclaim:
    """Reclaim, race, and capability tests for session_offer_with_ownership."""

    def test_claude_aliases_use_claude_manifest_directory(self, tmp_path):
        """Claude executor aliases resolve the canonical Claude manifest path."""
        ws = str(tmp_path)
        manifest_dir = os.path.join(ws, "runtime", "harness", "claude")
        os.makedirs(manifest_dir, exist_ok=True)
        with open(
            os.path.join(manifest_dir, "manifest.json"),
            "w",
            encoding="utf-8",
        ) as handle:
            json.dump({"supports": {"command_source": "shared_yoke_registry"}}, handle)

        for executor in ("claude-code", "claude-vscode"):
            result = resolve_harness_capabilities(executor, ws)

            assert result["manifest_executor"] == "claude-code"
            assert result["manifest_directory"] == "claude"
            assert result["source"] == "shared_registry"
            # A manifest declaring no limitations inherits the registry set
            # verbatim, so compare against the registry rather than a literal
            # that goes stale the moment a routable path is added.
            assert result["downstream_paths"] == shared_downstream_paths()

    def test_surface_specific_executor_uses_shared_registry(self, ownership_conn):
        """surface executors inherit shared registry truth through coarse manifest."""
        _conn, ws = ownership_conn
        manifest_dir = os.path.join(ws, "runtime", "harness", "codex")
        os.makedirs(manifest_dir, exist_ok=True)
        with open(
            os.path.join(manifest_dir, "manifest.json"), "w", encoding="utf-8"
        ) as handle:
            json.dump({"supports": {"command_source": "shared_yoke_registry"}}, handle)

        result = resolve_harness_capabilities("codex-desktop", ws)

        assert result["manifest_executor"] == "codex"
        assert result["manifest_directory"] == "codex"
        assert result["source"] == "shared_registry"
        assert result["downstream_paths"] == shared_downstream_paths()

    def test_offer_envelope_includes_supported_paths(self, ownership_conn):
        """Offer envelope persisted in DB includes supported_paths."""
        conn, ws = ownership_conn
        _ensure_active_session(conn, "sess-envelope-1", ws, model="opus")
        session_offer_with_ownership(
            conn,
            session_id="sess-envelope-1",
            executor="claude-code",
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
        """Session_offer_with_ownership auto-reclaims
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
               VALUES ('stale-sess', 'claude-code', 'anthropic', 'claude', '/tmp', %s, %s)""",
            (stale_iso, stale_iso),
        )
        _insert_item_claim(conn, "stale-sess", 100, stale_iso)
        conn.commit()

        result = session_offer_with_ownership(
            conn,
            session_id="new-sess-reclaim",
            executor="claude-code",
            provider="anthropic",
            model="opus",
            workspace=ws,
        )

        # The offering session should acquire the item
        assert result["action_hint"] == "charge"
        assert result["new_claim"] is not None
        assert result["new_claim"]["scope"] == {"item_id": 100}

        # The stale claim should be released
        stale_claim = _claim_row(conn, "stale-sess", 100)
        assert stale_claim["released_at"] is not None
        assert stale_claim["release_reason"] == "reclaimed"

    def test_offer_reclaims_ended_session_claim(self, ownership_conn):
        """Session_offer_with_ownership auto-reclaims
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
               VALUES ('ended-sess', 'claude-code', 'anthropic', 'claude', '/tmp', %s, %s, %s)""",
            (ended_iso, ended_iso, ended_iso),
        )
        _insert_item_claim(conn, "ended-sess", 100, ended_iso)
        conn.commit()

        result = session_offer_with_ownership(
            conn,
            session_id="new-sess-ended",
            executor="claude-code",
            provider="anthropic",
            model="opus",
            workspace=ws,
        )

        assert result["action_hint"] == "charge"
        assert result["new_claim"] is not None
        assert result["new_claim"]["scope"] == {"item_id": 100}

    def test_offer_only_stale_work_returns_charge(self, ownership_conn):
        """If only stale-claimed work exists on the frontier,
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
               VALUES ('sole-stale', 'claude-code', 'anthropic', 'claude', '/tmp', %s, %s)""",
            (stale_iso, stale_iso),
        )
        _insert_item_claim(conn, "sole-stale", 100, stale_iso)
        conn.commit()

        result = session_offer_with_ownership(
            conn,
            session_id="rescuer-sess",
            executor="claude-code",
            provider="anthropic",
            model="opus",
            workspace=ws,
        )

        # Must NOT return no_work -- must recover the stale item
        assert result["action_hint"] == "charge"
        assert result["new_claim"] is not None

    def test_offer_race_safe_no_duplicate_claims(self, ownership_conn):
        """If a live session holds the claim, reclaim does
        not release it, preserving single-owner safety."""
        conn, ws = ownership_conn
        _ensure_active_session(conn, "competing-sess", ws, model="opus")
        fresh_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        # Create a live session with a fresh claim on item 100
        conn.execute(
            """INSERT INTO harness_sessions
               (session_id, executor, provider, model, workspace, offered_at, last_heartbeat)
               VALUES ('live-sess', 'claude-code', 'anthropic', 'claude', '/tmp', %s, %s)""",
            (fresh_iso, fresh_iso),
        )
        _insert_item_claim(conn, "live-sess", 100, fresh_iso)
        conn.commit()

        result = session_offer_with_ownership(
            conn,
            session_id="competing-sess",
            executor="claude-code",
            provider="anthropic",
            model="opus",
            workspace=ws,
        )

        # The live claim is NOT reclaimed -- competing session gets no_work
        assert result["action_hint"] == "no_work"
        # The live claim is still active
        live_claim = _claim_row(conn, "live-sess", 100)
        assert live_claim["released_at"] is None
