"""session-touch CLI tests for yoke_core.api.service_client.

Shared fixture/helpers live in ``test_service_client_sessions_helpers.py``.
"""

from __future__ import annotations

import json

from runtime.api.fixtures.file_test_db import connect_test_db
from runtime.api.test_service_client import _run_client
from runtime.api.test_service_client_sessions_helpers import (
    session_offer_db,  # noqa: F401 — re-exported fixture
)


class TestSessionTouchCommand:
    """Tests for service_client.py session-touch command."""

    def _create_session(self, session_offer_db, sid):
        """Helper to create a session via session-begin."""
        return _run_client(
            [
                "session-begin",
                "--session-id", sid,
                "--executor", "claude-code",
                "--provider", "anthropic",
                "--model", "opus",
                "--workspace", session_offer_db["tmp_dir"],
                "--project-id", "1",
            ],
            db_path=session_offer_db["db_path"],
        )

    def test_session_touch_heartbeats_active_session(self, session_offer_db):
        """AC-3: session-touch heartbeats an active session."""
        sid = "touch-heartbeat"
        db = session_offer_db["db_path"]
        r = self._create_session(session_offer_db, sid)
        assert r.returncode == 0

        # Backdate heartbeat
        conn = connect_test_db(db)
        conn.execute(
            "UPDATE harness_sessions SET last_heartbeat = '2026-04-01T00:00:00Z' WHERE session_id = %s",
            (sid,),
        )
        conn.commit()
        conn.close()

        r2 = _run_client(["session-touch", "--session-id", sid], db_path=db)
        assert r2.returncode == 0, f"stderr: {r2.stderr}"
        data = json.loads(r2.stdout)
        assert data["success"] is True

        # Verify heartbeat was updated
        conn = connect_test_db(db)
        row = conn.execute(
            "SELECT last_heartbeat FROM harness_sessions WHERE session_id = %s",
            (sid,),
        ).fetchone()
        conn.close()
        assert row[0] != "2026-04-01T00:00:00Z"

    def test_session_touch_with_mode_updates_mode(self, session_offer_db):
        """AC-4: session-touch with --mode heartbeats AND updates mode."""
        sid = "touch-mode"
        db = session_offer_db["db_path"]
        r = self._create_session(session_offer_db, sid)
        assert r.returncode == 0

        r2 = _run_client(
            ["session-touch", "--session-id", sid, "--mode", "shepherd"],
            db_path=db,
        )
        assert r2.returncode == 0, f"stderr: {r2.stderr}"
        data = json.loads(r2.stdout)
        assert data["success"] is True
        assert data["session"]["mode"] == "shepherd"

        # Verify in DB
        conn = connect_test_db(db)
        row = conn.execute(
            "SELECT mode FROM harness_sessions WHERE session_id = %s",
            (sid,),
        ).fetchone()
        conn.close()
        assert row[0] == "shepherd"

    def test_session_touch_nonexistent_returns_exit_1(self, session_offer_db):
        """AC-5: session-touch on non-existent session returns exit 1."""
        db = session_offer_db["db_path"]
        r = _run_client(
            ["session-touch", "--session-id", "no-such-session"],
            db_path=db,
        )
        assert r.returncode == 1
        assert "not found" in r.stderr
        assert "session-begin" in r.stderr

    def test_session_touch_ended_session_returns_exit_1(self, session_offer_db):
        """AC-6: session-touch on ended session returns exit 1."""
        sid = "touch-ended"
        db = session_offer_db["db_path"]
        r = self._create_session(session_offer_db, sid)
        assert r.returncode == 0

        # End the session
        r_end = _run_client(
            ["session-end", "--session-id", sid],
            db_path=db,
        )
        assert r_end.returncode == 0

        r2 = _run_client(
            ["session-touch", "--session-id", sid],
            db_path=db,
        )
        assert r2.returncode == 1
        assert "has ended" in r2.stderr
        assert "inactive session" in r2.stderr
