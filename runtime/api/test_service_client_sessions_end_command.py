"""Tests for service_client.py session-end and session-end-if-empty commands."""

from __future__ import annotations

import json
from datetime import datetime, timezone

from runtime.api.fixtures.file_test_db import connect_test_db
from runtime.api.test_service_client import _run_client
from runtime.api.test_service_client_sessions_helpers import _pre_register_session
from yoke_core.domain.sessions import claim_work

pytest_plugins = ("runtime.api.test_service_client_sessions_helpers",)


_FRESH_TS = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
ITEM_ID = 10
ITEM_REF = f"YOK-{ITEM_ID}"


def _claim_item(db, session_id):
    conn = connect_test_db(db)
    try:
        claim_work(conn, session_id=session_id, item_id=10)
    finally:
        conn.close()


class TestSessionEndCommand:
    """Tests for service_client.py session-end command."""

    def test_session_end_auto_releases_active_claims(self, session_offer_db):
        """Session-end (no flags) auto-releases claims and ends.

        Detailed released_claims payload assertions live in the sibling
        test_service_client_sessions_end_claim_release.py.
        """
        sid = "end-test-sess"
        ws = session_offer_db["tmp_dir"]
        db = session_offer_db["db_path"]
        _pre_register_session(db, sid, workspace=ws)
        _claim_item(db, sid)

        r2 = _run_client(["session-end", "--session-id", sid], db_path=db)
        assert r2.returncode == 0, f"stderr: {r2.stderr}"
        data = json.loads(r2.stdout)
        assert data["success"] is True
        assert data["session"]["ended_at"] is not None
        assert len(data["released_claims"]) >= 1

    def test_session_end_succeeds_without_claims(self, session_offer_db):
        """session-end succeeds when no active claims."""
        sid = "end-no-claim-sess"
        ws = session_offer_db["tmp_dir"]
        db = session_offer_db["db_path"]
        _pre_register_session(db, sid, workspace=ws)
        r2 = _run_client(["session-end", "--session-id", sid], db_path=db)
        assert r2.returncode == 0
        data = json.loads(r2.stdout)
        assert data["success"] is True

    def test_session_end_idempotent(self, session_offer_db):
        """session-end on already-ended session exits 0 (best-effort)."""
        sid = "end-idem-sess"
        ws = session_offer_db["tmp_dir"]
        db = session_offer_db["db_path"]
        # Create session without claims (just register, don't offer which may claim)
        _pre_register_session(
            db,
            sid,
            executor="claude-code",
            provider="a",
            requested_model="o",
            workspace=ws,
        )
        # End first time
        r1 = _run_client(["session-end", "--session-id", sid], db_path=db)
        assert r1.returncode == 0

        # Second end should not fail (already_ended best-effort)
        r2 = _run_client(["session-end", "--session-id", sid], db_path=db)
        assert r2.returncode == 0
        data = json.loads(r2.stdout)
        assert data["success"] is True
        assert data.get("already_ended") is True

    def test_session_end_nonexistent_session(self, session_offer_db):
        """session-end on nonexistent session exits 0 (best-effort)."""
        r = _run_client(
            ["session-end", "--session-id", "nonexistent"],
            db_path=session_offer_db["db_path"],
        )
        assert r.returncode == 0
        data = json.loads(r.stdout)
        assert data["success"] is True


class TestSessionEndIfEmptyCommand:
    """Tests for service_client.py session-end-if-empty command."""

    def test_session_end_if_empty_ends_claimless_session(self, session_offer_db):
        sid = "end-if-empty-claimless"
        db = session_offer_db["db_path"]

        _pre_register_session(db, sid, workspace=session_offer_db["tmp_dir"])

        result = _run_client(["session-end-if-empty", "--session-id", sid], db_path=db)
        assert result.returncode == 0, f"stderr: {result.stderr}"
        data = json.loads(result.stdout)
        assert data["success"] is True
        assert data["status"] == "ended"
        assert data["ended"] is True

        conn = connect_test_db(db)
        row = conn.execute(
            "SELECT ended_at FROM harness_sessions WHERE session_id = %s", (sid,)
        ).fetchone()
        conn.close()
        assert row is not None
        assert row[0] is not None

    def test_session_end_if_empty_preserves_claimed_session(self, session_offer_db):
        sid = "end-if-empty-claimed"
        ws = session_offer_db["tmp_dir"]
        db = session_offer_db["db_path"]

        _pre_register_session(db, sid, workspace=ws)
        _claim_item(db, sid)

        result = _run_client(["session-end-if-empty", "--session-id", sid], db_path=db)
        assert result.returncode == 0, f"stderr: {result.stderr}"
        data = json.loads(result.stdout)
        assert data["success"] is True
        assert data["status"] == "has_claims"
        assert data["ended"] is False
        assert data["active_claim_count"] >= 1

        conn = connect_test_db(db)
        row = conn.execute(
            "SELECT ended_at FROM harness_sessions WHERE session_id = %s", (sid,)
        ).fetchone()
        claim = conn.execute(
            "SELECT COUNT(*) FROM work_claims WHERE session_id = %s AND released_at IS NULL",
            (sid,),
        ).fetchone()
        conn.close()
        assert row is not None
        assert row[0] is None
        assert claim[0] >= 1

    def test_session_end_if_empty_is_best_effort_for_missing_session(
        self, session_offer_db
    ):
        result = _run_client(
            ["session-end-if-empty", "--session-id", "nonexistent"],
            db_path=session_offer_db["db_path"],
        )
        assert result.returncode == 0
        data = json.loads(result.stdout)
        assert data["success"] is True
        assert data["status"] == "not_found"
