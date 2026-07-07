"""session-checkpoint CLI tests for yoke_core.api.service_client.

Shared fixture/helpers live in ``test_service_client_sessions_helpers.py``.
"""

from __future__ import annotations

import json

from runtime.api.fixtures.file_test_db import connect_test_db
from runtime.api.test_service_client import _run_client
from runtime.api.test_service_client_sessions_helpers import (
    _pre_register_session,
    session_offer_db,  # noqa: F401 — re-exported fixture
)


class TestSessionCheckpointCommand:
    """Tests for session-checkpoint and session-checkpoint-read."""

    def test_checkpoint_write_and_read_round_trip(self, session_offer_db):
        """AC-1, AC-2: checkpoint persisted and readable via CLI."""
        sid = "cp-test-sess"
        ws = session_offer_db["tmp_dir"]
        db = session_offer_db["db_path"]
        # Create session via session-begin, then offer
        _pre_register_session(db, sid, workspace=ws)
        r_offer = _run_client(
            [
                "session-offer", "--executor", "DARIUS",
                "--provider", "anthropic", "--model", "opus",
                "--workspace", ws, "--session-id", sid,
            ],
            db_path=db,
        )
        assert r_offer.returncode == 0

        # Write checkpoint
        r_write = _run_client(
            [
                "session-checkpoint",
                "--session-id", sid,
                "--step", "1",
                "--action", "charge",
                "--chainable", "true",
                "--item-id", "YOK-9999",
            ],
            db_path=db,
        )
        assert r_write.returncode == 0
        cp = json.loads(r_write.stdout)
        assert cp["step"] == 1
        assert cp["action"] == "charge"
        assert cp["chainable"] is True
        assert cp["item_id"] == "YOK-9999"

        # Read checkpoint
        r_read = _run_client(
            ["session-checkpoint-read", "--session-id", sid],
            db_path=db,
        )
        assert r_read.returncode == 0
        read_cp = json.loads(r_read.stdout)
        assert read_cp["step"] == 1
        assert read_cp["action"] == "charge"

    def test_checkpoint_read_empty_when_none(self, session_offer_db):
        """session-checkpoint-read returns {} when no checkpoint exists."""
        sid = "cp-empty-sess"
        ws = session_offer_db["tmp_dir"]
        db = session_offer_db["db_path"]
        _pre_register_session(db, sid, executor="D", provider="a", model="o", workspace=ws)
        _run_client(
            [
                "session-offer", "--executor", "D", "--provider", "a",
                "--model", "o", "--workspace", ws, "--session-id", sid,
            ],
            db_path=db,
        )
        r = _run_client(
            ["session-checkpoint-read", "--session-id", sid],
            db_path=db,
        )
        assert r.returncode == 0
        assert json.loads(r.stdout) == {}

    def test_checkpoint_on_ended_session_fails(self, session_offer_db):
        """session-checkpoint on ended session returns error."""
        sid = "cp-ended-sess"
        ws = session_offer_db["tmp_dir"]
        db = session_offer_db["db_path"]
        # Register without offer (no claims) so session-end succeeds
        _pre_register_session(db, sid, executor="D", provider="a", model="o", workspace=ws)
        _run_client(["session-end", "--session-id", sid], db_path=db)

        r = _run_client(
            [
                "session-checkpoint",
                "--session-id", sid,
                "--step", "1", "--action", "charge", "--chainable", "true",
            ],
            db_path=db,
        )
        assert r.returncode == 1

    def test_checkpointed_chain_step_supports_second_next_action_event(self, session_offer_db, monkeypatch):
        """AC-3, AC-7: checkpointed chain steps preserve second-offer lineage."""
        sid = "cp-chain-reoffer"
        ws = session_offer_db["tmp_dir"]
        db = session_offer_db["db_path"]

        _pre_register_session(db, sid, workspace=ws)
        r_offer_1 = _run_client(
            [
                "session-offer", "--executor", "DARIUS",
                "--provider", "anthropic", "--model", "opus",
                "--workspace", ws, "--session-id", sid, "--step", "1",
            ],
            db_path=db,
        )
        assert r_offer_1.returncode == 0
        d1 = json.loads(r_offer_1.stdout)
        assert d1["action"] == "charge"
        assert d1["chainable"] is True

        selected_item = d1["context"]["selected_item"]
        r_checkpoint = _run_client(
            [
                "session-checkpoint",
                "--session-id", sid,
                "--step", "1",
                "--action", d1["action"],
                "--chainable", "true",
                "--item-id", selected_item,
            ],
            db_path=db,
        )
        assert r_checkpoint.returncode == 0

        r_read = _run_client(
            ["session-checkpoint-read", "--session-id", sid],
            db_path=db,
        )
        assert r_read.returncode == 0
        checkpoint = json.loads(r_read.stdout)
        assert checkpoint["step"] == 1
        assert checkpoint["action"] == "charge"
        assert checkpoint["chainable"] is True
        assert checkpoint["item_id"] == selected_item

        r_offer_2 = _run_client(
            [
                "session-offer", "--executor", "DARIUS",
                "--provider", "anthropic", "--model", "opus",
                "--workspace", ws, "--session-id", sid, "--step", "2",
            ],
            db_path=db,
        )
        assert r_offer_2.returncode == 0
        d2 = json.loads(r_offer_2.stdout)
        assert d2["action"] == "resume"
        assert d2["chainable"] is True
        assert d2["context"]["item_id"] == selected_item

        # events now go to the DB via native Python emitter,
        # not to an ndjson capture file. Query the events table directly.
        conn = connect_test_db(db)
        rows = conn.execute(
            "SELECT event_name, envelope FROM events "
            "WHERE session_id = %s ORDER BY created_at",
            (sid,),
        ).fetchall()
        conn.close()

        next_actions = [
            json.loads(row[1])
            for row in rows if row[0] == "NextActionChosen"
        ]
        assert [e["context"]["step"] for e in next_actions] == [1, 2]

        chain_steps = [
            json.loads(row[1])
            for row in rows if row[0] == "ChainStepCompleted"
        ]
        assert len(chain_steps) == 1
        chain_ctx = chain_steps[0]["context"]
        assert chain_ctx["step"] == 1
        assert chain_ctx["action"] == "charge"
        assert chain_ctx["chainable"] is True
        assert chain_ctx["item_id"] == selected_item.removeprefix("YOK-")
