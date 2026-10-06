"""session-checkpoint CLI tests for yoke_core.api.service_client.

Shared fixture/helpers live in ``test_service_client_sessions_helpers.py``.
"""

from __future__ import annotations

import json

from runtime.api.test_service_client import _run_client
from runtime.api.test_service_client_sessions_helpers import (
    _pre_register_session,
)

pytest_plugins = ("runtime.api.test_service_client_sessions_helpers",)


class TestSessionCheckpointCommand:
    """Tests for session-checkpoint and session-checkpoint-read."""

    def test_checkpoint_write_and_read_round_trip(self, session_offer_db):
        """Checkpoint persisted and readable via CLI."""
        sid = "cp-test-sess"
        ws = session_offer_db["tmp_dir"]
        db = session_offer_db["db_path"]
        # Create session via session-begin
        _pre_register_session(db, sid, workspace=ws)

        # Write checkpoint
        r_write = _run_client(
            [
                "session-checkpoint",
                "--session-id",
                sid,
                "--step",
                "1",
                "--action",
                "charge",
                "--chainable",
                "true",
                "--item-id",
                "YOK-10",
            ],
            db_path=db,
        )
        assert r_write.returncode == 0
        cp = json.loads(r_write.stdout)
        assert cp["step"] == 1
        assert cp["action"] == "charge"
        assert cp["chainable"] is True
        assert cp["item_id"] == 10

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
        _pre_register_session(
            db,
            sid,
            executor="claude-code",
            provider="a",
            requested_model="o",
            workspace=ws,
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
        # Register without claims so session-end succeeds
        _pre_register_session(
            db,
            sid,
            executor="claude-code",
            provider="a",
            requested_model="o",
            workspace=ws,
        )
        _run_client(["session-end", "--session-id", sid], db_path=db)

        r = _run_client(
            [
                "session-checkpoint",
                "--session-id",
                sid,
                "--step",
                "1",
                "--action",
                "charge",
                "--chainable",
                "true",
            ],
            db_path=db,
        )
        assert r.returncode == 1
