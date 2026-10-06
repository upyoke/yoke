"""Session registration retries and reactivation preserve identity."""

import json

from runtime.api.fixtures.file_test_db import connect_test_db
from runtime.api.test_service_client import _run_client
from runtime.api.test_service_client_sessions_helpers import (
    session_test_db as session_test_db,
)


class TestSessionRegistrationReentry:
    def test_session_begin_idempotent_on_existing_session(self, session_test_db):
        """session-begin on an already-active session returns success."""
        sid = "begin-idempotent"
        args = [
            "session-begin",
            "--session-id",
            sid,
            "--executor",
            "claude-code",
            "--provider",
            "anthropic",
            "--model",
            "opus",
            "--workspace",
            session_test_db["tmp_dir"],
            "--project-id",
            "1",
        ]
        r1 = _run_client(args, db_path=session_test_db["db_path"])
        assert r1.returncode == 0, f"stderr: {r1.stderr}"
        d1 = json.loads(r1.stdout)
        assert d1["success"] is True

        # Second call should also succeed (idempotent)
        r2 = _run_client(args, db_path=session_test_db["db_path"])
        assert r2.returncode == 0, f"stderr: {r2.stderr}"
        d2 = json.loads(r2.stdout)
        assert d2["success"] is True
        assert d2.get("already_registered") is True

    def test_session_begin_reactivates_ended_session(self, session_test_db):
        """session-begin on an ended session reopens it as active.

        Executor is write-once.  The original executor value
        persists across reactivation; provider/model/lane refresh from the
        new register call.
        """
        sid = "begin-reactivate"
        first_args = [
            "session-begin",
            "--session-id",
            sid,
            "--executor",
            "claude-code",
            "--provider",
            "anthropic",
            "--model",
            "opus-old",
            "--workspace",
            session_test_db["tmp_dir"],
            "--project-id",
            "1",
        ]
        r1 = _run_client(first_args, db_path=session_test_db["db_path"])
        assert r1.returncode == 0, f"stderr: {r1.stderr}"
        first_data = json.loads(r1.stdout)
        original_offered_at = first_data["session"]["offered_at"]

        rend = _run_client(
            ["session-end", "--session-id", sid], db_path=session_test_db["db_path"]
        )
        assert rend.returncode == 0, f"stderr: {rend.stderr}"

        second_args = [
            "session-begin",
            "--session-id",
            sid,
            "--executor",
            "codex",
            "--provider",
            "openai",
            "--model",
            "gpt-5.4",
            "--workspace",
            session_test_db["tmp_dir"],
            "--project-id",
            "1",
        ]
        r2 = _run_client(second_args, db_path=session_test_db["db_path"])
        assert r2.returncode == 0, f"stderr: {r2.stderr}"
        d2 = json.loads(r2.stdout)
        assert d2["success"] is True
        assert d2.get("already_registered") is not True

        conn = connect_test_db(session_test_db["db_path"])
        row = conn.execute(
            "SELECT executor, provider, model, ended_at, offered_at FROM harness_sessions WHERE session_id = %s",
            (sid,),
        ).fetchone()
        conn.close()

        assert row is not None
        # Stored executor is the original INSERT value, not the
        # second-call argument.  Provider/model/etc. still refresh.
        assert row[0] == "claude-code"
        assert row[1] == "openai"
        assert row[2] == "gpt-5.4"
        assert row[3] is None
        assert row[4] == original_offered_at
