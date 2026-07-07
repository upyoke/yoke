"""Tests for service_client.py session-end and session-end-if-empty commands."""

from __future__ import annotations

import json
from datetime import datetime, timezone

from runtime.api.fixtures.file_test_db import connect_test_db
from runtime.api.test_service_client import _run_client
from runtime.api.test_service_client_sessions_helpers import session_offer_db, _pre_register_session  # noqa: F401
from runtime.api.test_constants import TEST_MODEL_ID


_FRESH_TS = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
ITEM_ID = 10
ITEM_REF = f"YOK-{ITEM_ID}"


class TestSessionEndCommand:
    """Tests for service_client.py session-end command."""

    def test_session_end_auto_releases_active_claims(self, session_offer_db):
        """AC-1/AC-11: session-end (no flags) auto-releases claims and ends.

        Detailed released_claims payload assertions live in the sibling
        test_service_client_sessions_end_claim_release.py.
        """
        sid = "end-test-sess"
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
        r2 = _run_client(
            ["session-end", "--session-id", sid],
            db_path=db,
        )
        assert r2.returncode == 0
        data = json.loads(r2.stdout)
        assert data["success"] is True

    def test_session_end_idempotent(self, session_offer_db):
        """session-end on already-ended session exits 0 (best-effort)."""
        sid = "end-idem-sess"
        ws = session_offer_db["tmp_dir"]
        db = session_offer_db["db_path"]
        # Create session without claims (just register, don't offer which may claim)
        _pre_register_session(db, sid, executor="D", provider="a", model="o", workspace=ws)
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

    def test_session_end_chain_pending_fails_without_force(self, session_offer_db):
        """CHAIN_PENDING is a real CLI failure without an explicit override."""
        sid = "end-chain-pending"
        checkpoint = {
            "step": 1,
            "action": "resume",
            "chainable": True,
            "handler_outcome": "completed",
            "item_id": ITEM_REF,
            "status": "reviewed-implementation",
            "required_path": "polish",
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
               (session_id, target_kind, item_id, claim_type, claimed_at, last_heartbeat)
               VALUES (%s, 'item', 10, 'exclusive', %s, %s)""",
            (sid, _FRESH_TS, _FRESH_TS),
        )
        conn.commit()
        conn.close()

        result = _run_client(["session-end", "--session-id", sid], db_path=session_offer_db["db_path"])
        assert result.returncode == 1
        data = json.loads(result.stdout)
        assert data["success"] is False
        assert data["code"] == "CHAIN_PENDING"

    def test_session_end_force_alone_still_returns_chain_pending(self, session_offer_db):
        """AC-9 / AC-13: ``--force`` alone no longer bypasses CHAIN_PENDING via the CLI."""
        sid = "end-chain-force"
        checkpoint = {
            "step": 1,
            "action": "resume",
            "chainable": True,
            "handler_outcome": "completed",
            "item_id": ITEM_REF,
            "status": "reviewed-implementation",
            "required_path": "polish",
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
               (session_id, target_kind, item_id, claim_type, claimed_at, last_heartbeat)
               VALUES (%s, 'item', 10, 'exclusive', %s, %s)""",
            (sid, _FRESH_TS, _FRESH_TS),
        )
        conn.commit()
        conn.close()

        result = _run_client(
            ["session-end", "--session-id", sid, "--force"],
            db_path=session_offer_db["db_path"],
        )
        assert result.returncode == 1
        data = json.loads(result.stdout)
        assert data["success"] is False
        assert data["code"] == "CHAIN_PENDING"

    def test_session_end_override_without_rationale_returns_2(self, session_offer_db):
        """AC-9 / AC-13: ``--override-chain-end`` without rationale fails fast at exit 2."""
        sid = "end-empty-rationale"
        checkpoint = {
            "step": 1, "action": "resume", "chainable": True,
            "handler_outcome": "completed",
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
            [
                "session-end", "--session-id", sid,
                "--override-chain-end", "--chain-end-rationale", "   ",
            ],
            db_path=session_offer_db["db_path"],
        )
        assert result.returncode == 2
        data = json.loads(result.stdout)
        assert data["success"] is False
        assert data["code"] == "OVERRIDE_RATIONALE_REQUIRED"

    def test_session_end_override_with_rationale_no_claims_succeeds(self, session_offer_db):
        """AC-9 / AC-13: ``--override-chain-end --chain-end-rationale TEXT`` ends the session."""
        sid = "end-override-noclaim"
        checkpoint = {
            "step": 1, "action": "resume", "chainable": True,
            "handler_outcome": "completed",
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
            [
                "session-end", "--session-id", sid,
                "--override-chain-end",
                "--chain-end-rationale", "operator override — harness restart",
            ],
            db_path=session_offer_db["db_path"],
        )
        assert result.returncode == 0
        data = json.loads(result.stdout)
        assert data["success"] is True


class TestSessionEndIfEmptyCommand:
    """Tests for service_client.py session-end-if-empty command."""

    def test_session_end_if_empty_ends_claimless_session(self, session_offer_db):
        sid = "end-if-empty-claimless"
        db = session_offer_db["db_path"]

        _pre_register_session(db, sid, workspace=session_offer_db["tmp_dir"])

        result = _run_client(
            ["session-end-if-empty", "--session-id", sid],
            db_path=db,
        )
        assert result.returncode == 0, f"stderr: {result.stderr}"
        data = json.loads(result.stdout)
        assert data["success"] is True
        assert data["status"] == "ended"
        assert data["ended"] is True

        conn = connect_test_db(db)
        row = conn.execute(
            "SELECT ended_at FROM harness_sessions WHERE session_id = %s",
            (sid,),
        ).fetchone()
        conn.close()
        assert row is not None
        assert row[0] is not None

    def test_session_end_if_empty_preserves_claimed_session(self, session_offer_db):
        sid = "end-if-empty-claimed"
        ws = session_offer_db["tmp_dir"]
        db = session_offer_db["db_path"]

        _pre_register_session(db, sid, workspace=ws)
        offer = _run_client(
            [
                "session-offer", "--executor", "DARIUS",
                "--provider", "anthropic", "--model", "opus",
                "--workspace", ws, "--session-id", sid,
            ],
            db_path=db,
        )
        assert offer.returncode == 0, f"stderr: {offer.stderr}"

        result = _run_client(
            ["session-end-if-empty", "--session-id", sid],
            db_path=db,
        )
        assert result.returncode == 0, f"stderr: {result.stderr}"
        data = json.loads(result.stdout)
        assert data["success"] is True
        assert data["status"] == "has_claims"
        assert data["ended"] is False
        assert data["active_claim_count"] >= 1

        conn = connect_test_db(db)
        row = conn.execute(
            "SELECT ended_at FROM harness_sessions WHERE session_id = %s",
            (sid,),
        ).fetchone()
        claim = conn.execute(
            "SELECT COUNT(*) FROM work_claims WHERE session_id = %s AND released_at IS NULL",
            (sid,),
        ).fetchone()
        conn.close()
        assert row is not None
        assert row[0] is None
        assert claim[0] >= 1

    def test_session_end_if_empty_is_best_effort_for_missing_session(self, session_offer_db):
        result = _run_client(
            ["session-end-if-empty", "--session-id", "nonexistent"],
            db_path=session_offer_db["db_path"],
        )
        assert result.returncode == 0
        data = json.loads(result.stdout)
        assert data["success"] is True
        assert data["status"] == "not_found"