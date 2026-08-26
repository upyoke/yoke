"""Tests for service_client.py claim-cleanup and session-heartbeat commands."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from runtime.api.fixtures.file_test_db import connect_test_db
from runtime.api.test_service_client import _run_client
from runtime.api.test_service_client_sessions_helpers import _pre_register_session
from yoke_core.domain.work_claim_targets import make_item_target

pytest_plugins = ("runtime.api.test_service_client_sessions_helpers",)


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
               (session_id, target_kind, scope, claim_type, claimed_at, last_heartbeat)
               VALUES ('stale-sess', 'item', %s, 'exclusive', %s, %s)""",
            (make_item_target(10).scope_json(), _STALE_TS, _STALE_TS),
        )
        conn.commit()
        conn.close()

        result = _run_client(
            ["release-done-claims", "--item-id", "YOK-10"],
            db_path=db,
        )
        assert result.returncode == 0
        data = json.loads(result.stdout)
        assert data["success"] is True
        assert data["released"] == 1
        assert data["item_id"] == "10"

        conn = connect_test_db(db)
        target = make_item_target(10)
        row = conn.execute(
            "SELECT released_at, release_reason FROM work_claims "
            "WHERE target_kind = %s AND scope = %s",
            (target.kind, target.scope_json()),
        ).fetchone()
        assert row["released_at"] is not None
        assert row["release_reason"] == "completed"
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
                "session-offer",
                "--session-id",
                sid,
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
                "session-offer",
                "--session-id",
                sid,
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
