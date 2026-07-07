"""Session lifecycle tests for the chain-end override contract.

Sibling of ``test_sessions_lifecycle_chain.py``. Covers the structural
override path that replaced the legacy ``force=True`` CHAIN_PENDING
bypass — the override flag plus a non-empty rationale is now the only
way past the guard, and the override emits ``ChainDeclineOverridden``
with the checkpoint and operator context.
"""

from __future__ import annotations

import json

import pytest
from unittest.mock import patch

from runtime.api.test_sessions import (
    _register,
    conn,  # noqa: F401  (pytest fixture)
)
from yoke_core.domain.sessions import (
    SessionError,
    claim_work,
    end_session,
    release_claim,
    update_chain_checkpoint,
)


ITEM_ID = "100"
ITEM_REF = f"YOK-{ITEM_ID}"


def _setup_chain_pending(conn, session_id="sess-chain"):
    """Register a session with a chainable checkpoint at step 1/3 + claim."""
    _register(conn, session_id=session_id)
    claim_work(conn, session_id=session_id, item_id=ITEM_REF)
    update_chain_checkpoint(
        conn, session_id,
        step=1, action="charge", chainable=True,
        handler_outcome="completed", item_id=ITEM_REF,
    )
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


class TestChainEndOverrideContract:
    """Structural CHAIN_PENDING guard and explicit override path."""

    @patch("yoke_core.domain.sessions_analytics._emit_session_event")
    def test_force_alone_does_not_bypass_chain_pending(self, mock_emit, conn):
        """``force=True`` alone is no longer a bypass.

        The structural guard now requires the explicit override flag plus
        a non-empty rationale. ``force=True`` without those is rejected
        even when the active-claim guard would otherwise pass.
        """
        _setup_chain_pending(conn)
        claim_row = conn.execute(
            "SELECT id FROM work_claims WHERE session_id='sess-chain' AND released_at IS NULL"
        ).fetchone()
        release_claim(conn, claim_row["id"], reason="completed")
        with pytest.raises(SessionError) as exc_info:
            end_session(conn, "sess-chain", force=True)
        assert exc_info.value.code == "CHAIN_PENDING"

    @patch("yoke_core.domain.sessions_analytics._emit_session_event")
    def test_override_chain_end_without_rationale_does_not_bypass(self, mock_emit, conn):
        """Empty rationale is treated as missing — guard still fires."""
        _setup_chain_pending(conn)
        claim_row = conn.execute(
            "SELECT id FROM work_claims WHERE session_id='sess-chain' AND released_at IS NULL"
        ).fetchone()
        release_claim(conn, claim_row["id"], reason="completed")
        with pytest.raises(SessionError) as exc_info:
            end_session(
                conn,
                "sess-chain",
                override_chain_end=True,
                chain_end_rationale="   ",
            )
        assert exc_info.value.code == "CHAIN_PENDING"

    def test_override_chain_end_with_rationale_bypasses_and_emits_event(self, conn):
        """Override + rationale ends the session and emits ChainDeclineOverridden.

        Event carries session_id, checkpoint step, max_chain_steps,
        action, item_id, override_flag, and the operator-supplied
        rationale.
        """
        _setup_chain_pending(conn)
        claim_row = conn.execute(
            "SELECT id FROM work_claims WHERE session_id='sess-chain' AND released_at IS NULL"
        ).fetchone()
        release_claim(conn, claim_row["id"], reason="completed")

        captured: list[dict] = []

        def _capture(name, **kwargs):
            captured.append({"name": name, **kwargs})

        with patch("yoke_core.domain.events.emit_event", side_effect=_capture):
            with patch("yoke_core.domain.sessions_analytics._emit_session_event"):
                result = end_session(
                    conn,
                    "sess-chain",
                    override_chain_end=True,
                    chain_end_rationale="urgent: harness crash recovery",
                )

        assert result["ended_at"] is not None
        override_calls = [c for c in captured if c["name"] == "ChainDeclineOverridden"]
        assert len(override_calls) == 1
        ctx = override_calls[0]["context"]
        assert ctx["session_id"] == "sess-chain"
        assert ctx["checkpoint_step"] == 1
        assert ctx["max_chain_steps"] == 3
        assert ctx["rationale"] == "urgent: harness crash recovery"
        assert ctx["action"] == "charge"
        assert ctx["item_id"] == ITEM_ID
        assert ctx["override_flag"] == "force_chain_end"

    def test_end_session_uses_shared_chain_pending_state_helper(self, conn):
        """AC-2: ``_end_session`` reads the chain checkpoint via the shared helper.

        Locks in the contract that future changes to "what counts as
        chain-pending" land in :func:`_chain_pending_state` rather than
        duplicating the logic in either end path. We patch the helper
        and verify ``end_session`` consults it before deciding.
        """
        from yoke_core.domain import sessions_render_end as _sre

        _setup_chain_pending(conn, session_id="sess-helper")
        claim_row = conn.execute(
            "SELECT id FROM work_claims WHERE session_id='sess-helper' AND released_at IS NULL"
        ).fetchone()
        release_claim(conn, claim_row["id"], reason="completed")

        original_state = _sre._chain_pending_state(conn, "sess-helper")
        with patch.object(
            _sre, "_chain_pending_state",
            return_value=original_state,
        ) as mock_state:
            with patch("yoke_core.domain.sessions_analytics._emit_session_event"):
                with pytest.raises(SessionError) as exc_info:
                    end_session(conn, "sess-helper")
        assert exc_info.value.code == "CHAIN_PENDING"
        mock_state.assert_called_once()

    @patch("yoke_core.domain.sessions_analytics._emit_session_event")
    def test_override_does_not_emit_when_no_chain_pending(self, mock_emit, conn):
        """Override is a no-op for the audit event when there is nothing to override.

        Passing override_chain_end + rationale on a session with no pending
        chainable checkpoint ends normally and does not emit
        ChainDeclineOverridden — the event is only meaningful when the
        guard would have fired.
        """
        _register(conn, session_id="sess-no-pending")
        captured: list[dict] = []
        with patch(
            "yoke_core.domain.events.emit_event",
            side_effect=lambda name, **kw: captured.append({"name": name, **kw}),
        ):
            result = end_session(
                conn,
                "sess-no-pending",
                override_chain_end=True,
                chain_end_rationale="defensive override on no-pending session",
            )
        assert result["ended_at"] is not None
        assert not [c for c in captured if c["name"] == "ChainDeclineOverridden"]
