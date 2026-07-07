"""Session lifecycle tests: chain checkpoint and CHAIN_PENDING guard.

Covers update_chain_checkpoint / read_chain_checkpoint and the
end_session CHAIN_PENDING guard. Active-claim guard, claim-release on
session end, and the human-only operator override are split into sibling
modules:

- ``test_sessions_lifecycle_active_claim.py`` — TestActiveClaimGuard,
  TestSessionEndReleaseClaims.
- ``test_sessions_lifecycle_operator_override.py`` —
  TestOperatorOverrideReleaseClaim.
"""

from __future__ import annotations

import json

import pytest
from unittest.mock import patch

from runtime.api.test_sessions import (
    _register,
    conn,
    ownership_conn,
    _ensure_active_session,
)
from yoke_core.domain.sessions import (
    SessionError,
    claim_work,
    end_session,
    read_chain_checkpoint,
    release_claim,
    update_chain_checkpoint,
)


def _sun(item_id: int) -> str:
    return f"YOK-{item_id}"


class TestChainCheckpoint:
    """Tests for update_chain_checkpoint / read_chain_checkpoint."""

    def test_write_checkpoint_persists_on_offer_envelope(self, conn):
        _register(conn, session_id="chain-sess")
        cp = update_chain_checkpoint(
            conn,
            "chain-sess",
            step=1,
            action="charge",
            chainable=True,
            item_id=_sun(9999),
        )
        assert cp["step"] == 1
        assert cp["action"] == "charge"
        assert cp["chainable"] is True
        assert cp["item_id"] == _sun(9999)
        assert cp["handler_outcome"] == "completed"
        assert "completed_at" in cp

        # Verify persisted in offer_envelope
        row = conn.execute(
            "SELECT offer_envelope FROM harness_sessions WHERE session_id = 'chain-sess'"
        ).fetchone()
        envelope = json.loads(row["offer_envelope"])
        assert "chain_checkpoint" in envelope
        assert envelope["chain_checkpoint"]["step"] == 1

    def test_read_checkpoint_returns_persisted_data(self, conn):
        _register(conn, session_id="read-sess")
        update_chain_checkpoint(
            conn, "read-sess", step=2, action="resume", chainable=False
        )
        cp = read_chain_checkpoint(conn, "read-sess")
        assert cp is not None
        assert cp["step"] == 2
        assert cp["action"] == "resume"
        assert cp["chainable"] is False

    def test_read_checkpoint_returns_none_when_absent(self, conn):
        _register(conn, session_id="no-cp-sess")
        cp = read_chain_checkpoint(conn, "no-cp-sess")
        assert cp is None

    def test_read_checkpoint_returns_none_for_unknown_session(self, conn):
        cp = read_chain_checkpoint(conn, "nonexistent")
        assert cp is None

    def test_checkpoint_preserves_existing_envelope_data(self, conn):
        envelope = {"session_id": "env-sess", "executor": "test", "step": 1}
        _register(conn, session_id="env-sess", offer_envelope=envelope)
        update_chain_checkpoint(
            conn, "env-sess", step=1, action="charge", chainable=True
        )
        row = conn.execute(
            "SELECT offer_envelope FROM harness_sessions WHERE session_id = 'env-sess'"
        ).fetchone()
        env = json.loads(row["offer_envelope"])
        # Original keys preserved
        assert env["executor"] == "test"
        # Checkpoint added
        assert env["chain_checkpoint"]["action"] == "charge"

    def test_checkpoint_overwrites_previous_checkpoint(self, conn):
        _register(conn, session_id="overwrite-sess")
        update_chain_checkpoint(
            conn, "overwrite-sess", step=1, action="charge", chainable=True
        )
        update_chain_checkpoint(
            conn, "overwrite-sess", step=2, action="resume", chainable=True
        )
        cp = read_chain_checkpoint(conn, "overwrite-sess")
        assert cp["step"] == 2
        assert cp["action"] == "resume"

    def test_checkpoint_includes_task_num_when_provided(self, conn):
        _register(conn, session_id="task-sess")
        cp = update_chain_checkpoint(
            conn, "task-sess", step=1, action="resume", chainable=True,
            item_id=_sun(100), task_num=3,
        )
        assert cp["task_num"] == 3

    def test_checkpoint_on_ended_session_raises(self, conn):
        _register(conn, session_id="ended-sess")
        end_session(conn, "ended-sess")
        with pytest.raises(SessionError) as exc_info:
            update_chain_checkpoint(
                conn, "ended-sess", step=1, action="charge", chainable=True
            )
        assert exc_info.value.code == "SESSION_ENDED"

    def test_checkpoint_on_unknown_session_raises(self, conn):
        with pytest.raises(SessionError) as exc_info:
            update_chain_checkpoint(
                conn, "ghost", step=1, action="charge", chainable=True
            )
        assert exc_info.value.code == "NOT_FOUND"

    @patch("yoke_core.domain.sessions_analytics._emit_event")
    def test_checkpoint_emits_chain_step_completed_event(self, mock_emit, conn):
        from yoke_core.domain.sessions import EVENT_CHAIN_STEP_COMPLETED
        _register(conn, session_id="event-sess")
        update_chain_checkpoint(
            conn, "event-sess", step=1, action="charge", chainable=True,
            item_id=_sun(50),
        )
        # Find the ChainStepCompleted call
        calls = [c for c in mock_emit.call_args_list
                 if c[0][0] == EVENT_CHAIN_STEP_COMPLETED]
        assert len(calls) == 1
        call_kwargs = calls[0][1]
        assert call_kwargs["session_id"] == "event-sess"
        assert call_kwargs["item_id"] == _sun(50)
        ctx = call_kwargs["context"]
        assert ctx["step"] == 1
        assert ctx["action"] == "charge"
        assert ctx["chainable"] is True


# ---------------------------------------------------------------------------
# CHAIN_PENDING guard in end_session
# ---------------------------------------------------------------------------


class TestEndSessionChainPendingGuard:
    """FR-1: end_session with CHAIN_PENDING guard."""

    def _setup_chain_pending(self, conn, session_id="sess-chain"):
        """Register a session with a chainable checkpoint at step 1/3."""
        _register(conn, session_id=session_id)
        claim_work(conn, session_id=session_id, item_id=_sun(100))
        # Persist a chainable checkpoint
        update_chain_checkpoint(
            conn, session_id,
            step=1, action="charge", chainable=True,
            handler_outcome="completed", item_id=_sun(100),
        )
        # Persist max_chain_steps in offer_envelope
        row = conn.execute(
            "SELECT offer_envelope FROM harness_sessions WHERE session_id=%s",
            (session_id,),
        ).fetchone()
        envelope = json.loads(row["offer_envelope"]) if row["offer_envelope"] else {}
        envelope["max_chain_steps"] = 3
        conn.execute(
            "UPDATE harness_sessions SET offer_envelope=%s WHERE session_id=%s",
            (json.dumps(envelope), session_id),
        )
        conn.commit()

    @patch("yoke_core.domain.sessions_analytics._emit_session_event")
    def test_chain_pending_blocks_normal_end(self, mock_emit, conn):
        """AC-1: Normal end with pending chainable checkpoint raises CHAIN_PENDING."""
        self._setup_chain_pending(conn)
        with pytest.raises(SessionError) as exc_info:
            end_session(conn, "sess-chain")
        assert exc_info.value.code == "CHAIN_PENDING"
        # Verify session is still active
        row = conn.execute(
            "SELECT ended_at FROM harness_sessions WHERE session_id='sess-chain'"
        ).fetchone()
        assert row["ended_at"] is None
        # Verify claims are still held
        claims = conn.execute(
            "SELECT COUNT(*) FROM work_claims WHERE session_id='sess-chain' AND released_at IS NULL"
        ).fetchone()
        assert claims[0] > 0

    @patch("yoke_core.domain.sessions_analytics._emit_session_event")
    def test_no_checkpoint_allows_end(self, mock_emit, conn):
        """AC-2: No checkpoint means normal end succeeds."""
        _register(conn, session_id="sess-no-cp")
        result = end_session(conn, "sess-no-cp")
        assert result["ended_at"] is not None

    @patch("yoke_core.domain.sessions_analytics._emit_session_event")
    def test_not_chainable_allows_end(self, mock_emit, conn):
        """AC-2: Non-chainable checkpoint allows normal end (claims pre-released)."""
        _register(conn, session_id="sess-nc")
        c = claim_work(conn, session_id="sess-nc", item_id=_sun(200))
        release_claim(conn, c["id"], reason="completed")
        update_chain_checkpoint(
            conn, "sess-nc",
            step=1, action="feed", chainable=False,
            handler_outcome="completed",
        )
        result = end_session(conn, "sess-nc")
        assert result["ended_at"] is not None

    @patch("yoke_core.domain.sessions_analytics._emit_session_event")
    def test_exhausted_chain_allows_end(self, mock_emit, conn):
        """AC-2: step >= max_chain_steps allows normal end."""
        _register(conn, session_id="sess-exh")
        update_chain_checkpoint(
            conn, "sess-exh",
            step=3, action="charge", chainable=True,
            handler_outcome="completed",
        )
        # max_chain_steps defaults to 3, step=3 >= 3
        result = end_session(conn, "sess-exh")
        assert result["ended_at"] is not None

    @patch("yoke_core.domain.sessions_analytics._emit_session_event")
    def test_missing_max_defaults_to_three(self, mock_emit, conn):
        """Historical envelopes without max_chain_steps default to 3."""
        _register(conn, session_id="sess-old")
        update_chain_checkpoint(
            conn, "sess-old",
            step=1, action="charge", chainable=True,
            handler_outcome="completed",
        )
        # Ensure offer_envelope has no max_chain_steps
        row = conn.execute(
            "SELECT offer_envelope FROM harness_sessions WHERE session_id='sess-old'"
        ).fetchone()
        envelope = json.loads(row["offer_envelope"]) if row["offer_envelope"] else {}
        envelope.pop("max_chain_steps", None)
        conn.execute(
            "UPDATE harness_sessions SET offer_envelope=%s WHERE session_id=%s",
            (json.dumps(envelope), "sess-old"),
        )
        conn.commit()
        # step 1 < default 3, chainable=True -> should block
        with pytest.raises(SessionError) as exc_info:
            end_session(conn, "sess-old")
        assert exc_info.value.code == "CHAIN_PENDING"
