"""CLI regression for session-end-if-empty's chain-pending decline branch.

Sibling of ``test_service_client_sessions_end_command.py`` per the
spec File Budget plan — the parent module is already at the 350-line
authored-file ceiling, so the chain-pending JSON-shape regressions
land here instead of growing the parent further.

Covers two of the four shapes from AC-7 that surface through the CLI
boundary (the other two — ``has_claims`` and the no-checkpoint
``ended`` cases — already have CLI coverage in the parent module):

  (c) ``claim_count == 0`` and chainable checkpoint within budget ->
      ``chain_pending`` with a ``next_action`` resume hint and
      ``ChainEndDeferred`` evidence in the events ledger.
  (d) ``claim_count == 0`` and chainable checkpoint at budget
      exhaustion (``step >= max_chain_steps``) -> ``ended``.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

from runtime.api.fixtures.file_test_db import connect_test_db
from runtime.api.test_service_client import _run_client
from runtime.api.test_service_client_sessions_helpers import (  # noqa: F401
    session_offer_db,
)
from runtime.api.test_constants import TEST_MODEL_ID


_FRESH_TS = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
ITEM_ID = 10
ITEM_REF = f"YOK-{ITEM_ID}"


class TestSessionEndIfEmptyChainPending:
    """Two CLI-boundary shapes specific to the chain-pending decline branch."""

    def test_session_end_if_empty_returns_chain_pending_with_next_action(
        self, session_offer_db,
    ):
        """A claimless session with a chainable checkpoint must not be ended.

        The CLI returns ``status='chain_pending'`` plus a ``next_action``
        resume command so the next agent turn (or the operator) can pick
        up the chain. The session row stays alive — the heartbeat-stale
        reclaim path remains the safety net for genuinely abandoned
        chains.
        """
        sid = "end-if-empty-chain-pending"
        checkpoint = {
            "step": 1,
            "action": "charge",
            "chainable": True,
            "handler_outcome": "completed",
            "item_id": ITEM_REF,
            "status": "reviewed-implementation",
            "required_path": "advance",
        }
        conn = connect_test_db(session_offer_db["db_path"])
        conn.execute(
            f"""INSERT INTO harness_sessions
               (session_id, executor, provider, model, workspace, offer_envelope,
                offered_at, last_heartbeat)
               VALUES (%s, 'DARIUS', 'anthropic', '{TEST_MODEL_ID}', %s, %s, %s, %s)""",
            (
                sid,
                session_offer_db["tmp_dir"],
                json.dumps({"max_chain_steps": 3, "chain_checkpoint": checkpoint}),
                _FRESH_TS,
                _FRESH_TS,
            ),
        )
        conn.execute(
            """INSERT INTO work_claims
               (session_id, target_kind, item_id, claim_type, claimed_at,
                last_heartbeat, released_at, release_reason)
               VALUES (%s, 'item', 10, 'exclusive', %s, %s, %s, 'handed_off')""",
            (sid, _FRESH_TS, _FRESH_TS, _FRESH_TS),
        )
        conn.commit()
        conn.close()

        result = _run_client(
            ["session-end-if-empty", "--session-id", sid],
            db_path=session_offer_db["db_path"],
        )
        assert result.returncode == 0
        data = json.loads(result.stdout)
        assert data["success"] is True
        assert data["status"] == "chain_pending"
        assert data["ended"] is False
        assert data["active_claim_count"] == 0
        assert data["checkpoint_step"] == 1
        assert data["max_chain_steps"] == 3
        assert data["chainable"] is True
        assert data["handler_outcome"] == "completed"
        assert data["item_id"] == str(ITEM_ID)
        assert data["triggered_by"] == "stop-hook"
        assert "--executor DARIUS" in data["next_action"]
        assert "--provider anthropic" in data["next_action"]
        # ``--model`` is no longer echoed — session-offer resolves the canonical
        # model from harness_sessions.model.
        assert "--model " not in data["next_action"]
        assert f"--workspace {session_offer_db['tmp_dir']}" in data["next_action"]
        assert "--lane DARIUS" in data["next_action"]
        assert "session-offer" in data["next_action"]
        assert "--step 2" in data["next_action"]
        assert sid in data["next_action"]
        assert data["last_release_at"] is not None

        conn = connect_test_db(session_offer_db["db_path"])
        row = conn.execute(
            "SELECT ended_at FROM harness_sessions WHERE session_id = %s", (sid,)
        ).fetchone()
        event_row = conn.execute(
            """SELECT item_id, envelope FROM events
               WHERE event_name = 'ChainEndDeferred' AND session_id = %s""",
            (sid,),
        ).fetchone()
        conn.close()
        assert row is not None
        assert row[0] is None
        assert event_row is not None
        assert event_row[0] == str(ITEM_ID)
        envelope = json.loads(event_row[1])
        assert envelope["context"]["item_id"] == str(ITEM_ID)
        assert envelope["context"]["triggered_by"] == "stop-hook"

    def test_session_end_if_empty_ends_when_chain_budget_exhausted(
        self, session_offer_db,
    ):
        """AC-7 shape (d): chainable but ``step >= max_chain_steps`` -> ``ended``."""
        sid = "end-if-empty-chain-exhausted"
        checkpoint = {
            "step": 3, "action": "charge", "chainable": True,
            "handler_outcome": "completed", "item_id": ITEM_REF,
        }
        conn = connect_test_db(session_offer_db["db_path"])
        conn.execute(
            f"""INSERT INTO harness_sessions
               (session_id, executor, provider, model, workspace, offer_envelope,
                offered_at, last_heartbeat)
               VALUES (%s, 'DARIUS', 'anthropic', '{TEST_MODEL_ID}', %s, %s, %s, %s)""",
            (
                sid,
                session_offer_db["tmp_dir"],
                json.dumps({"max_chain_steps": 3, "chain_checkpoint": checkpoint}),
                _FRESH_TS,
                _FRESH_TS,
            ),
        )
        conn.commit()
        conn.close()

        result = _run_client(
            ["session-end-if-empty", "--session-id", sid],
            db_path=session_offer_db["db_path"],
        )
        assert result.returncode == 0
        data = json.loads(result.stdout)
        assert data["success"] is True
        assert data["status"] == "ended"
        assert data["ended"] is True
