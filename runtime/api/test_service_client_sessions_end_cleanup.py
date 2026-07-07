"""Tests for service_client.py claim-cleanup and session-heartbeat commands."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from yoke_core.domain import db_backend
from runtime.api.fixtures.file_test_db import connect_test_db
from runtime.api.test_service_client import _run_client
from runtime.api.test_service_client_sessions_helpers import session_offer_db, _pre_register_session  # noqa: F401
from runtime.api.test_constants import TEST_MODEL_ID


# Precomputed 30-minutes-ago timestamp for tests exercising the
# stale-session / stale-claim cleanup paths.  Portable-SQL tests cannot use
# a SQL-side past-offset literal inline; the cleanup helpers query against
# "last N minutes" windows so we need a real past literal bound from Python.
_STALE_TS = (datetime.now(timezone.utc) - timedelta(minutes=30)).strftime(
    "%Y-%m-%dT%H:%M:%SZ"
)


class TestClaimCleanupCommands:
    """Tests for service_client.py cleanup helpers added in."""

    def test_release_done_claims_releases_item_claims(self, session_offer_db):
        db = session_offer_db["db_path"]
        conn = connect_test_db(db)
        conn.execute(
            """INSERT INTO harness_sessions
               (session_id, executor, provider, model, execution_lane, workspace, mode, offered_at, last_heartbeat)
               VALUES ('stale-sess', 'codex', 'openai', 'gpt-5.4', 'primary', %s, 'charge', %s, %s)""",
            (session_offer_db["tmp_dir"], _STALE_TS, _STALE_TS),
        )
        conn.execute(
            """INSERT INTO work_claims
               (session_id, target_kind, item_id, claim_type, claimed_at, last_heartbeat)
               VALUES ('stale-sess', 'item', 9999, 'exclusive', %s, %s)""",
            (_STALE_TS, _STALE_TS),
        )
        conn.commit()
        conn.close()

        result = _run_client(
            ["release-done-claims", "--item-id", "YOK-9999"],
            db_path=db,
        )
        assert result.returncode == 0
        data = json.loads(result.stdout)
        assert data["success"] is True
        assert data["released"] == 1
        assert data["item_id"] == "9999"

        conn = connect_test_db(db)
        row = conn.execute(
            "SELECT released_at, release_reason FROM work_claims "
            "WHERE target_kind='item' AND item_id = 9999",
        ).fetchone()
        assert row["released_at"] is not None
        assert row["release_reason"] == "completed"
        conn.close()

    def test_clean_stale_sessions_reclaims_never_engaged(self, session_offer_db):
        # Use claude-code executor so the reclaim TTL is the
        # base threshold (Codex has a 60-minute override so a 30-minute stale
        # codex session would legitimately be 'between_turns' and skipped).
        db = session_offer_db["db_path"]
        conn = connect_test_db(db)
        conn.execute(
            f"""INSERT INTO harness_sessions
               (session_id, executor, provider, model, execution_lane, workspace, mode, offered_at, last_heartbeat)
               VALUES ('never-engaged-sess', 'claude-code', 'anthropic', '{TEST_MODEL_ID}', 'primary', %s, 'charge', %s, %s)""",
            (session_offer_db["tmp_dir"], _STALE_TS, _STALE_TS),
        )
        conn.execute(
            """INSERT INTO work_claims
               (session_id, target_kind, item_id, claim_type, claimed_at, last_heartbeat)
               VALUES ('never-engaged-sess', 'item', 43, 'exclusive', %s, %s)""",
            (_STALE_TS, _STALE_TS),
        )
        conn.commit()
        conn.close()

        result = _run_client(
            ["clean-stale-sessions", "--threshold-minutes", "10"],
            db_path=db,
        )
        assert result.returncode == 0
        data = json.loads(result.stdout)
        assert data["success"] is True
        assert len(data["never_engaged"]) == 1
        assert data["never_engaged"][0]["session_id"] == "never-engaged-sess"
        assert data["total_reclaimed"] == 1
        conn = connect_test_db(db)
        session_row = conn.execute(
            "SELECT ended_at FROM harness_sessions WHERE session_id = 'never-engaged-sess'",
        ).fetchone()
        assert session_row["ended_at"] is not None
        claim_row = conn.execute(
            "SELECT released_at, release_reason FROM work_claims "
            "WHERE target_kind='item' AND item_id = 43",
        ).fetchone()
        assert claim_row["released_at"] is not None
        assert claim_row["release_reason"] == "reclaimed"
        conn.close()

    def test_clean_stale_sessions_skips_session_with_recent_tool_activity(
        self, session_offer_db,
    ):
        """AC-10/AC-13: CLI uses the unified activity classifier.

        A session with a stale heartbeat but a recent ``HarnessToolCallCompleted``
        event is NOT reclaimed by ``clean-stale-sessions``. Proves the
        operator command inherits the helper-driven activity signal.
        """
        db = session_offer_db["db_path"]
        recent_ts = (
            datetime.now(timezone.utc) - timedelta(minutes=2)
        ).strftime("%Y-%m-%dT%H:%M:%SZ")
        conn = connect_test_db(db)
        conn.execute(
            f"""INSERT INTO harness_sessions
               (session_id, executor, provider, model, execution_lane,
                workspace, mode, offered_at, last_heartbeat)
               VALUES ('busy-sess', 'claude-code', 'anthropic',
                       '{TEST_MODEL_ID}', 'primary', %s, 'charge', %s, %s)""",
            (session_offer_db["tmp_dir"], _STALE_TS, _STALE_TS),
        )
        # Recent tool activity (the column the observe pipeline stamps)
        # keeps the session alive under the unified activity classifier
        # even though the heartbeat is stale.
        conn.execute(
            """UPDATE harness_sessions
               SET last_tool_call_at = %s,
                   tool_call_count = COALESCE(tool_call_count, 0) + 1
               WHERE session_id = 'busy-sess'""",
            (recent_ts,),
        )
        conn.commit()
        conn.close()

        result = _run_client(
            ["clean-stale-sessions", "--threshold-minutes", "10"],
            db_path=db,
        )
        assert result.returncode == 0
        data = json.loads(result.stdout)
        assert data["success"] is True
        assert data["total_reclaimed"] == 0

        conn = connect_test_db(db)
        sess_row = conn.execute(
            "SELECT ended_at FROM harness_sessions WHERE session_id = 'busy-sess'",
        ).fetchone()
        assert sess_row["ended_at"] is None
        conn.close()


class TestSessionHeartbeatCommand:
    """Tests for service_client.py session-heartbeat command."""

    def test_session_heartbeat_refreshes_session_and_claim(self, session_offer_db):
        sid = "heartbeat-test-sess"
        ws = session_offer_db["tmp_dir"]
        db = session_offer_db["db_path"]

        _pre_register_session(db, sid, workspace=ws)
        r1 = _run_client(
            [
                "session-offer", "--executor", "DARIUS",
                "--provider", "anthropic", "--model", "opus",
                "--workspace", ws, "--session-id", sid,
            ],
            db_path=db,
        )
        assert r1.returncode == 0

        conn = connect_test_db(db)
        conn.execute(
            "UPDATE harness_sessions SET last_heartbeat = '2026-04-03T15:00:00Z' WHERE session_id = %s",
            (sid,),
        )
        conn.execute(
            "UPDATE work_claims SET last_heartbeat = '2026-04-03T15:00:00Z' WHERE session_id = %s",
            (sid,),
        )
        conn.commit()
        conn.close()

        r2 = _run_client(["session-heartbeat", "--session-id", sid], db_path=db)
        assert r2.returncode == 0
        data = json.loads(r2.stdout)
        assert data["success"] is True

        conn = connect_test_db(db)
        session_row = conn.execute(
            "SELECT last_heartbeat FROM harness_sessions WHERE session_id = %s",
            (sid,),
        ).fetchone()
        claim_row = conn.execute(
            "SELECT last_heartbeat FROM work_claims WHERE session_id = %s AND released_at IS NULL",
            (sid,),
        ).fetchone()
        assert session_row["last_heartbeat"] != "2026-04-03T15:00:00Z"
        assert claim_row["last_heartbeat"] != "2026-04-03T15:00:00Z"
        conn.close()

    def test_session_offer_updates_session_mode(self, session_offer_db):
        sid = "mode-test-sess"
        ws = session_offer_db["tmp_dir"]
        db = session_offer_db["db_path"]

        _pre_register_session(db, sid, workspace=ws)
        result = _run_client(
            [
                "session-offer", "--executor", "DARIUS",
                "--provider", "anthropic", "--model", "opus",
                "--workspace", ws, "--session-id", sid,
            ],
            db_path=db,
        )
        assert result.returncode == 0
        data = json.loads(result.stdout)
        assert data["action"] == "charge"

        conn = connect_test_db(db)
        row = conn.execute(
            "SELECT mode FROM harness_sessions WHERE session_id = %s",
            (sid,),
        ).fetchone()
        assert row["mode"] == "charge"
        conn.close()
