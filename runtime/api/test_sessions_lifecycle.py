"""Session lifecycle tests: register, heartbeat, end-if-empty.

Claim acquisition + release tests → test_sessions_lifecycle_claim.py
Stale detection + handoff + transaction safety → test_sessions_lifecycle_stale.py
"""

from __future__ import annotations

import pytest
from unittest.mock import patch

from runtime.api.test_constants import TEST_MODEL_ID
from runtime.api.test_sessions import (
    _p,
    _register,
    conn,  # noqa: F401  (pytest fixture)
)
from yoke_core.domain.sessions import (
    EVENT_HARNESS_SESSION_STARTED,
    SessionError,
    claim_work,
    end_session,
    end_session_if_empty,
    heartbeat,
    register_session,  # noqa: F401  (re-exported for downstream callers)
)


# ---------------------------------------------------------------------------
# Session registration tests
# ---------------------------------------------------------------------------


class TestRegisterSession:
    def test_register_creates_record(self, conn):
        result = _register(conn)
        assert result["session_id"] == "sess-1"
        assert result["executor"] == "DARIUS"
        assert result["provider"] == "anthropic"
        assert result["model"] == TEST_MODEL_ID
        assert result["execution_lane"] == "primary"
        assert result["workspace"] == "/tmp/work"
        assert result["mode"] == "wait"
        assert result["ended_at"] is None
        assert result["offered_at"] is not None
        assert result["last_heartbeat"] is not None

    def test_register_stores_capabilities_as_json(self, conn):
        result = _register(conn, capabilities=["browser", "shell"])
        assert result["capabilities"] == ["browser", "shell"]

    def test_register_stores_offer_envelope(self, conn):
        envelope = {"session_id": "sess-1", "extra": "data"}
        result = _register(conn, offer_envelope=envelope)
        assert result["offer_envelope"] == envelope

    def test_register_duplicate_session_fails(self, conn):
        _register(conn, session_id="dup")
        with pytest.raises(SessionError) as exc_info:
            _register(conn, session_id="dup")
        assert exc_info.value.code == "SESSION_EXISTS"

    def test_register_refreshes_placeholder_model_on_duplicate(self, conn):
        """VS Code registers the session with ``--model default`` (stored
        as the literal ``"default"``). A subsequent UserPromptSubmit's
        session-begin — armed with a real model ID from the transcript —
        must upgrade the stored placeholder even though the insert
        conflicts with SESSION_EXISTS.
        """
        _register(conn, session_id="vscode-sess", model="default")
        with pytest.raises(SessionError) as exc_info:
            _register(conn, session_id="vscode-sess", model=TEST_MODEL_ID)
        assert exc_info.value.code == "SESSION_EXISTS"

        row = conn.execute(
            f"SELECT model FROM harness_sessions WHERE session_id = {_p(conn)}",
            ("vscode-sess",),
        ).fetchone()
        assert row["model"] == TEST_MODEL_ID

    def test_register_does_not_overwrite_real_model_with_placeholder(self, conn):
        """Never downgrade a real model ID back to ``"default"``."""
        _register(conn, session_id="real-sess", model="claude-opus-4-7[1m]")
        with pytest.raises(SessionError) as exc_info:
            _register(conn, session_id="real-sess", model="default")
        assert exc_info.value.code == "SESSION_EXISTS"

        row = conn.execute(
            f"SELECT model FROM harness_sessions WHERE session_id = {_p(conn)}",
            ("real-sess",),
        ).fetchone()
        assert row["model"] == "claude-opus-4-7[1m]"

    def test_register_does_not_overwrite_real_model_with_different_real(self, conn):
        """The refresh is a placeholder → real upgrade only, not a
        free-for-all model swap on every prompt.
        """
        _register(conn, session_id="stable-sess", model=TEST_MODEL_ID)
        with pytest.raises(SessionError) as exc_info:
            _register(conn, session_id="stable-sess", model="claude-sonnet-4-6")
        assert exc_info.value.code == "SESSION_EXISTS"

        row = conn.execute(
            f"SELECT model FROM harness_sessions WHERE session_id = {_p(conn)}",
            ("stable-sess",),
        ).fetchone()
        assert row["model"] == TEST_MODEL_ID

    def test_reactivate_refuses_to_downgrade_real_model_to_placeholder(self, conn):
        """VS Code sessions auto-end between prompts (session-end-if-empty),
        then the next prompt re-fires SessionStart. The SessionStart payload
        has no ``model``, so the caller passes ``"unknown"``. That must not
        clobber the real model ID recovered during the previous turn's
        UserPromptSubmit transcript refresh.
        """
        _register(
            conn,
            session_id="vscode-reactivate",
            model="claude-sonnet-4-6",
            executor="claude-vscode",
        )
        end_session(conn, "vscode-reactivate")

        result = _register(
            conn,
            session_id="vscode-reactivate",
            model="unknown",
            executor="claude-vscode",
        )

        assert result["ended_at"] is None
        # Stored model stayed real, not downgraded to "unknown".
        assert result["model"] == "claude-sonnet-4-6"
        row = conn.execute(
            f"SELECT model FROM harness_sessions WHERE session_id = {_p(conn)}",
            ("vscode-reactivate",),
        ).fetchone()
        assert row["model"] == "claude-sonnet-4-6"

    def test_reactivate_upgrades_placeholder_stored_to_real_caller(self, conn):
        """The inverse: if the stored model was a placeholder (e.g. the
        session ended before UserPromptSubmit could refresh), the
        reactivation path should accept a real model from the caller.
        """
        _register(
            conn,
            session_id="vscode-upgrade",
            model="unknown",
            executor="claude-vscode",
        )
        end_session(conn, "vscode-upgrade")

        result = _register(
            conn,
            session_id="vscode-upgrade",
            model="claude-sonnet-4-6",
            executor="claude-vscode",
        )

        assert result["model"] == "claude-sonnet-4-6"

    def test_register_reactivates_ended_session(self, conn):
        # Executor is write-once.  The original canonical executor
        # value persists across reactivation; everything else
        # (model/mode/provider/workspace/lane) refreshes from the new
        # register call.
        original = _register(
            conn,
            session_id="reactivate-me",
            model="old-model",
            mode="wait",
            executor="claude-desktop",
        )
        end_session(conn, "reactivate-me")

        result = _register(
            conn,
            session_id="reactivate-me",
            model="new-model",
            mode="hook",
            executor="codex",
            provider="openai",
            workspace="/tmp/reopened",
            execution_lane="ALTMAN",
        )

        assert result["session_id"] == "reactivate-me"
        assert result["ended_at"] is None
        assert result["model"] == "new-model"
        assert result["mode"] == "hook"
        # Canonical executor unchanged from the initial INSERT,
        # even though the caller passed a different family on reactivation.
        # The original surface alias "claude-desktop" canonicalized to
        # "claude-code" and the surface is preserved in display_name.
        assert result["executor"] == "claude-code"
        assert result["executor_display_name"] == "claude-desktop"
        assert result["provider"] == "openai"
        assert result["workspace"] == "/tmp/reopened"
        assert result["execution_lane"] == "ALTMAN"
        assert result["offered_at"] == original["offered_at"]

    def test_register_executor_is_write_once_on_reentry(self, conn):
        """AC-2: SESSION_EXISTS path leaves stored executor untouched.

        The canonical executor and display alias both persist write-once
        from the first INSERT — a sibling surface arriving later does not
        rewrite the stored attribution.
        """
        _register(conn, session_id="write-once", executor="claude-desktop")
        # Re-register against the still-active session with a different surface
        with pytest.raises(SessionError) as exc_info:
            _register(conn, session_id="write-once", executor="claude-vscode")
        assert exc_info.value.code == "SESSION_EXISTS"

        row = conn.execute(
            "SELECT executor, executor_display_name "
            f"FROM harness_sessions WHERE session_id = {_p(conn)}",
            ("write-once",),
        ).fetchone()
        assert row["executor"] == "claude-code"
        assert row["executor_display_name"] == "claude-desktop"

    # YOK-1771 executor canonicalization + display-alias coverage lives
    # in ``test_sessions_lifecycle_executor.py`` so this module stays
    # under the 350-line authored-file cap.

    def test_register_session_event_uses_stored_executor_on_reactivation(self, conn):
        """AC-10: HarnessSessionStarted event reports the stored canonical
        executor and the preserved display alias.

        When a closed session is reactivated under a different executor arg,
        the stored canonical value (from the original INSERT) wins both in
        the DB row and in the emitted event context.
        """
        _register(conn, session_id="event-stored", executor="claude-desktop")
        end_session(conn, "event-stored")

        captured: list = []

        def _capture(event_name, **kwargs):
            captured.append((event_name, kwargs))

        with patch(
            "yoke_core.domain.sessions_analytics._emit_session_event",
            side_effect=_capture,
        ):
            _register(
                conn,
                session_id="event-stored",
                executor="codex",  # caller passes a different family
                provider="openai",
            )

        register_events = [
            kw for name, kw in captured if name == EVENT_HARNESS_SESSION_STARTED
        ]
        assert register_events, "HarnessSessionStarted should fire on reactivation"
        ctx = register_events[-1]["context"]
        # Event reflects the canonical stored executor + preserved display.
        assert ctx["executor"] == "claude-code"
        assert ctx["executor_display_name"] == "claude-desktop"

    def test_register_returns_all_identity_fields(self, conn):
        """AC-1: all identity fields from the session-identity contract."""
        result = _register(conn)
        for field in ("session_id", "executor", "provider", "model",
                       "execution_lane", "capabilities", "workspace",
                       "mode", "offered_at", "last_heartbeat", "ended_at"):
            assert field in result, f"Missing field: {field}"

# Slice 8 actor-id register tests live in
# ``test_sessions_lifecycle_actor_id.py`` to honour the file-line
# budget. Run that module alongside this one for full register coverage.


# ---------------------------------------------------------------------------
# Heartbeat tests
# ---------------------------------------------------------------------------


class TestHeartbeat:
    def test_heartbeat_updates_timestamp(self, conn):
        _register(conn)
        before = conn.execute(
            "SELECT last_heartbeat FROM harness_sessions WHERE session_id='sess-1'"
        ).fetchone()["last_heartbeat"]
        result = heartbeat(conn, "sess-1")
        # Heartbeat should be >= before (may be same second)
        assert result["last_heartbeat"] >= before

    def test_heartbeat_updates_claim_timestamps(self, conn):
        _register(conn)
        claim_work(conn, session_id="sess-1", item_id="YOK-9999")
        before_claim = conn.execute(
            "SELECT last_heartbeat FROM work_claims WHERE session_id='sess-1'"
        ).fetchone()["last_heartbeat"]
        heartbeat(conn, "sess-1")
        after_claim = conn.execute(
            "SELECT last_heartbeat FROM work_claims WHERE session_id='sess-1'"
        ).fetchone()["last_heartbeat"]
        assert after_claim >= before_claim

    def test_heartbeat_nonexistent_session_fails(self, conn):
        with pytest.raises(SessionError) as exc_info:
            heartbeat(conn, "nonexistent")
        assert exc_info.value.code == "NOT_FOUND"

    def test_heartbeat_ended_session_fails(self, conn):
        _register(conn)
        end_session(conn, "sess-1")
        with pytest.raises(SessionError) as exc_info:
            heartbeat(conn, "sess-1")
        assert exc_info.value.code == "SESSION_ENDED"


class TestEndSessionIfEmpty:
    def test_ends_claimless_active_session(self, conn):
        _register(conn, session_id="empty-end")

        result = end_session_if_empty(conn, "empty-end")

        assert result["status"] == "ended"
        assert result["ended"] is True
        row = conn.execute(
            "SELECT ended_at FROM harness_sessions WHERE session_id='empty-end'"
        ).fetchone()
        assert row["ended_at"] is not None

    def test_skips_session_with_active_claims(self, conn):
        _register(conn, session_id="claimed-end")
        claim_work(conn, session_id="claimed-end", item_id="YOK-9999")

        result = end_session_if_empty(conn, "claimed-end")

        assert result["status"] == "has_claims"
        assert result["ended"] is False
        assert result["active_claim_count"] == 1
        row = conn.execute(
            "SELECT ended_at FROM harness_sessions WHERE session_id='claimed-end'"
        ).fetchone()
        assert row["ended_at"] is None

    def test_idempotent_when_already_ended(self, conn):
        _register(conn, session_id="already-ended")
        end_session_if_empty(conn, "already-ended")

        result = end_session_if_empty(conn, "already-ended")

        assert result["status"] == "already_ended"
        assert result["ended"] is False
