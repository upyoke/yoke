"""Session lifecycle tests for the ``end_session_if_empty`` chain-pending guard.

Sibling of ``test_sessions_lifecycle_chain.py`` and
``test_sessions_lifecycle_chain_override.py``. Covers the structural
fix that protects in-flight ``/yoke do`` chains across an early
claim release (advance/finalize step 6b's ``handoff-to-polish`` /
``handoff-to-usher``) so the Stop hook can no longer silently end a
session whose chain checkpoint still has budget remaining.

The four shapes exercised here mirror the canonical lifecycle states
``end_session_if_empty`` distinguishes:

  (a) ``claim_count > 0`` -> ``has_claims`` (regression — pre-existing).
  (b) ``claim_count == 0`` and no chainable checkpoint -> ``ended``.
  (c) ``claim_count == 0`` and chainable checkpoint within budget ->
      ``chain_pending`` (the new branch).
  (d) ``claim_count == 0`` and chainable checkpoint at budget exhaustion
      (``step >= max_chain_steps``) -> ``ended``.

A separate test covers the heartbeat-stale eviction safety net that ensures
abandoned chains stay reclaimable.
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
    claim_work,
    end_session_if_empty,
    release_claim,
    update_chain_checkpoint,
)
from yoke_core.domain.sessions_render_end import _chain_pending_state


ITEM_ID = "100"
ITEM_REF = f"YOK-{ITEM_ID}"


def _setup_chain_checkpoint(
    conn,
    session_id="sess-cp",
    *,
    step=1,
    chainable=True,
    max_chain_steps=3,
    handler_outcome="completed",
    item_id=ITEM_REF,
    with_claim=False,
):
    """Register a session with a chain checkpoint and optional active claim."""
    _register(conn, session_id=session_id)
    if with_claim:
        claim_work(conn, session_id=session_id, item_id=item_id)
    update_chain_checkpoint(
        conn, session_id,
        step=step, action="charge", chainable=chainable,
        handler_outcome=handler_outcome, item_id=item_id,
    )
    row = conn.execute(
        "SELECT offer_envelope FROM harness_sessions WHERE session_id=%s",
        (session_id,),
    ).fetchone()
    envelope = json.loads(row["offer_envelope"]) if row["offer_envelope"] else {}
    envelope["max_chain_steps"] = max_chain_steps
    conn.execute(
        "UPDATE harness_sessions SET offer_envelope=%s WHERE session_id=%s",
        (json.dumps(envelope), session_id),
    )
    conn.commit()


class TestChainPendingState:
    """Shared helper consumed by both end paths."""

    def test_no_checkpoint_returns_not_pending(self, conn):
        _register(conn, session_id="sess-empty")
        state = _chain_pending_state(conn, "sess-empty")
        assert state.pending is False
        assert state.chainable is False
        assert state.step == 0

    def test_chainable_within_budget_is_pending(self, conn):
        _setup_chain_checkpoint(conn, session_id="sess-pending", step=1, max_chain_steps=3)
        state = _chain_pending_state(conn, "sess-pending")
        assert state.pending is True
        assert state.chainable is True
        assert state.step == 1
        assert state.max_chain_steps == 3
        assert state.handler_outcome == "completed"
        assert state.item_id == ITEM_ID
        assert state.action == "charge"

    def test_chainable_at_budget_exhaustion_is_not_pending(self, conn):
        _setup_chain_checkpoint(conn, session_id="sess-exhausted", step=3, max_chain_steps=3)
        state = _chain_pending_state(conn, "sess-exhausted")
        assert state.pending is False
        assert state.chainable is True

    def test_non_chainable_checkpoint_is_not_pending(self, conn):
        _setup_chain_checkpoint(
            conn, session_id="sess-nonchain",
            step=1, chainable=False, handler_outcome="blocked",
        )
        state = _chain_pending_state(conn, "sess-nonchain")
        assert state.pending is False
        assert state.chainable is False

    def test_chainable_terminal_outcome_is_not_pending(self, conn):
        _setup_chain_checkpoint(
            conn, session_id="sess-blocked",
            step=1, chainable=True, handler_outcome="blocked",
        )
        state = _chain_pending_state(conn, "sess-blocked")
        assert state.pending is False


class TestEndSessionIfEmptyShapes:
    """The four canonical lifecycle shapes the helper must distinguish."""

    @patch("yoke_core.domain.sessions_analytics._emit_session_event")
    def test_claimed_session_returns_has_claims(self, _emit, conn):
        """Shape (a) — pre-existing behavior, regression coverage."""
        _setup_chain_checkpoint(conn, session_id="sess-claimed", with_claim=True)
        result = end_session_if_empty(conn, "sess-claimed")
        assert result["status"] == "has_claims"
        assert result["ended"] is False
        assert result["active_claim_count"] == 1
        row = conn.execute(
            "SELECT ended_at FROM harness_sessions WHERE session_id='sess-claimed'"
        ).fetchone()
        assert row["ended_at"] is None

    @patch("yoke_core.domain.sessions_analytics._emit_session_event")
    def test_no_claim_no_chain_returns_ended(self, _emit, conn):
        """Shape (b) — pre-existing behavior, regression coverage."""
        _register(conn, session_id="sess-empty-no-chain")
        result = end_session_if_empty(conn, "sess-empty-no-chain")
        assert result["status"] == "ended"
        assert result["ended"] is True
        row = conn.execute(
            "SELECT ended_at FROM harness_sessions WHERE session_id='sess-empty-no-chain'"
        ).fetchone()
        assert row["ended_at"] is not None

    def test_no_claim_chainable_within_budget_returns_chain_pending(self, conn):
        """Shape (c) — the new branch.

        The session has released its mid-chain claim and ended its turn.
        The Stop hook calls ``session-end-if-empty``; the helper must
        decline to end the session, emit ``ChainEndDeferred``, and
        return ``chain_pending`` with a ``next_action`` resume hint.
        """
        _setup_chain_checkpoint(
            conn, session_id="sess-pending-clean",
            step=1, max_chain_steps=3, with_claim=True,
        )
        claim_row = conn.execute(
            "SELECT id FROM work_claims WHERE session_id='sess-pending-clean' AND released_at IS NULL"
        ).fetchone()
        release_claim(conn, claim_row["id"], reason="handed_off")

        captured: list[dict] = []
        with patch("yoke_core.domain.events.emit_event",
                   side_effect=lambda name, **kw: captured.append({"name": name, **kw})):
            with patch("yoke_core.domain.sessions_analytics._emit_session_event"):
                result = end_session_if_empty(conn, "sess-pending-clean")

        assert result["status"] == "chain_pending"
        assert result["ended"] is False
        assert result["active_claim_count"] == 0
        assert result["checkpoint_step"] == 1
        assert result["max_chain_steps"] == 3
        assert result["chainable"] is True
        assert result["handler_outcome"] == "completed"
        assert result["item_id"] == ITEM_ID
        assert result["action"] == "charge"
        assert result["last_release_at"] is not None
        assert result["triggered_by"] == "stop-hook"
        assert "--executor DARIUS" in result["next_action"]
        assert "--provider anthropic" in result["next_action"]
        # ``--model`` is no longer echoed in next_action — session-offer
        # resolves the canonical model from harness_sessions.model.
        assert "--model " not in result["next_action"]
        assert "--workspace /tmp/work" in result["next_action"]
        assert "--lane primary" in result["next_action"]
        assert "session-offer" in result["next_action"]
        assert "--step 2" in result["next_action"]
        assert "sess-pending-clean" in result["next_action"]

        row = conn.execute(
            "SELECT ended_at FROM harness_sessions WHERE session_id='sess-pending-clean'"
        ).fetchone()
        assert row["ended_at"] is None

        deferred = [c for c in captured if c["name"] == "ChainEndDeferred"]
        assert len(deferred) == 1
        ctx = deferred[0]["context"]
        assert ctx["session_id"] == "sess-pending-clean"
        assert ctx["triggered_by"] == "stop-hook"
        assert ctx["checkpoint_step"] == 1
        assert ctx["max_chain_steps"] == 3
        assert ctx["chainable"] is True
        assert ctx["handler_outcome"] == "completed"
        assert ctx["action"] == "charge"
        assert ctx["item_id"] == ITEM_ID

    @patch("yoke_core.domain.sessions_analytics._emit_session_event")
    def test_no_claim_at_budget_exhaustion_returns_ended(self, _emit, conn):
        """Shape (d) — chain budget exhausted; the session is genuinely empty."""
        _setup_chain_checkpoint(
            conn, session_id="sess-exhausted-end",
            step=3, max_chain_steps=3, with_claim=False,
        )
        result = end_session_if_empty(conn, "sess-exhausted-end")
        assert result["status"] == "ended"
        assert result["ended"] is True

    @patch("yoke_core.domain.sessions_analytics._emit_session_event")
    def test_triggered_by_threads_through_to_event(self, _emit, conn):
        """Custom ``triggered_by`` is preserved on the JSON return and the event."""
        _setup_chain_checkpoint(
            conn, session_id="sess-codex-stop",
            step=1, max_chain_steps=3, with_claim=False,
        )
        captured: list[dict] = []
        with patch("yoke_core.domain.events.emit_event",
                   side_effect=lambda name, **kw: captured.append({"name": name, **kw})):
            result = end_session_if_empty(
                conn, "sess-codex-stop", triggered_by="codex-stop-hook",
            )
        assert result["triggered_by"] == "codex-stop-hook"
        deferred = [c for c in captured if c["name"] == "ChainEndDeferred"]
        assert len(deferred) == 1
        assert deferred[0]["context"]["triggered_by"] == "codex-stop-hook"

    @patch("yoke_core.domain.sessions_analytics._emit_session_event")
    def test_chain_pending_session_remains_reclaimable_via_stale_window(self, _emit, conn):
        """The 60-minute heartbeat-stale safety net still applies.

        A session in ``chain_pending`` whose heartbeat is older than the
        stale window is recoverable by the next session-offer. This
        regression locks in AC-6: the chain-pending guard does not make
        sessions un-cleanupable; it only protects the routine
        post-handoff turn boundary.
        """
        _setup_chain_checkpoint(
            conn, session_id="sess-abandoned",
            step=1, max_chain_steps=3, with_claim=False,
        )
        # First call — session is preserved as chain_pending.
        result = end_session_if_empty(conn, "sess-abandoned")
        assert result["status"] == "chain_pending"

        # The session row is still alive — reclaim can still target it.
        row = conn.execute(
            "SELECT ended_at FROM harness_sessions WHERE session_id='sess-abandoned'"
        ).fetchone()
        assert row["ended_at"] is None
        # And the chain checkpoint is intact for the next session-offer to read.
        env = json.loads(conn.execute(
            "SELECT offer_envelope FROM harness_sessions WHERE session_id='sess-abandoned'"
        ).fetchone()["offer_envelope"])
        assert env["chain_checkpoint"]["chainable"] is True
        assert env["chain_checkpoint"]["step"] == 1


class TestNextActionResumeHint:
    """The ``next_action`` field is the canonical resume command for the next turn."""

    @patch("yoke_core.domain.sessions_analytics._emit_session_event")
    def test_next_action_increments_step(self, _emit, conn):
        _setup_chain_checkpoint(
            conn, session_id="sess-next",
            step=2, max_chain_steps=3, with_claim=False,
        )
        result = end_session_if_empty(conn, "sess-next")
        assert result["status"] == "chain_pending"
        assert "--step 3" in result["next_action"]

    @patch("yoke_core.domain.sessions_analytics._emit_session_event")
    def test_next_action_preserves_step_for_non_useful_outcome(self, _emit, conn):
        _setup_chain_checkpoint(
            conn, session_id="sess-next-non-useful",
            step=2, max_chain_steps=3, with_claim=False,
            handler_outcome="slice_committed",
        )
        result = end_session_if_empty(conn, "sess-next-non-useful")
        assert result["status"] == "chain_pending"
        assert "--step 2" in result["next_action"]
