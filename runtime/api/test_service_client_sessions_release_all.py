"""Tests for service_client release-all-claims, claim-release override, and
release-command registration."""

from __future__ import annotations

import json

import pytest

from runtime.api.fixtures.file_test_db import connect_test_db
from runtime.api.test_service_client import _run_client
from runtime.api.test_service_client_sessions_helpers import session_offer_db  # noqa: F401


class TestReleaseAllClaims:
    """Tests for release-all-claims command."""

    def test_release_all_claims_active_session(self, session_offer_db):
        """AC-4: release-all-claims releases all claims for a session."""
        db_path = session_offer_db["db_path"]
        sid = "release-all-test"

        conn = connect_test_db(db_path)
        conn.execute(
            "INSERT INTO harness_sessions (session_id, executor, provider, model, "
            "execution_lane, workspace, mode, offered_at, last_heartbeat) "
            "VALUES (%s, 'claude-code', 'anthropic', 'opus', 'primary', %s, 'hook', "
            "'2026-04-20T00:00:00Z', '2026-04-20T00:00:00Z')",
            (sid, session_offer_db["tmp_dir"]),
        )
        conn.execute(
            "INSERT INTO work_claims (session_id, target_kind, item_id, claim_type, claimed_at, "
            "last_heartbeat) VALUES (%s, 'item', 50, 'exclusive', "
            "'2026-04-20T00:00:00Z', '2026-04-20T00:00:00Z')",
            (sid,),
        )
        conn.execute(
            "INSERT INTO work_claims (session_id, target_kind, item_id, claim_type, claimed_at, "
            "last_heartbeat) VALUES (%s, 'item', 51, 'exclusive', "
            "'2026-04-20T00:00:00Z', '2026-04-20T00:00:00Z')",
            (sid,),
        )
        conn.commit()
        conn.close()

        result = _run_client(
            ["release-all-claims", "--session-id", sid, "--reason", "session_ended"],
            db_path=db_path,
        )
        assert result.returncode == 0, f"stderr: {result.stderr}"

        out = json.loads(result.stdout)
        assert out["success"] is True

        # Verify all claims released
        conn = connect_test_db(db_path)
        unreleased = conn.execute(
            "SELECT COUNT(*) FROM work_claims "
            "WHERE session_id = %s AND released_at IS NULL",
            (sid,),
        ).fetchone()[0]
        conn.close()
        assert unreleased == 0

    def test_release_all_claims_unknown_session(self, session_offer_db):
        """release-all-claims with unknown session exits 0 silently."""
        db_path = session_offer_db["db_path"]

        result = _run_client(
            ["release-all-claims", "--session-id", "nonexistent",
             "--reason", "cleanup"],
            db_path=db_path,
        )
        assert result.returncode == 0
        out = json.loads(result.stdout)
        assert out["success"] is True
        assert out.get("no_session") is True

    def test_session_stays_active_after_last_claim_release(self, session_offer_db):
        """AC-5: Releasing the last claim does NOT end the session."""
        db_path = session_offer_db["db_path"]
        sid = "release-last-claim-test"

        conn = connect_test_db(db_path)
        conn.execute(
            "INSERT INTO harness_sessions (session_id, executor, provider, model, "
            "execution_lane, workspace, mode, offered_at, last_heartbeat) "
            "VALUES (%s, 'claude-code', 'anthropic', 'opus', 'primary', %s, 'hook', "
            "'2026-04-20T00:00:00Z', '2026-04-20T00:00:00Z')",
            (sid, session_offer_db["tmp_dir"]),
        )
        conn.execute(
            "INSERT INTO work_claims (session_id, target_kind, item_id, claim_type, claimed_at, "
            "last_heartbeat) VALUES (%s, 'item', 77, 'exclusive', "
            "'2026-04-20T00:00:00Z', '2026-04-20T00:00:00Z')",
            (sid,),
        )
        conn.commit()
        conn.close()

        # Release the only claim
        result = _run_client(
            ["release-work-claim", "--session-id", sid,
             "--item", "YOK-77", "--reason", "done"],
            db_path=db_path,
        )
        assert result.returncode == 0

        # Session must still be active (ended_at IS NULL)
        conn = connect_test_db(db_path)
        row = conn.execute(
            "SELECT ended_at FROM harness_sessions WHERE session_id = %s",
            (sid,),
        ).fetchone()
        conn.close()
        assert row is not None
        assert row[0] is None, "Session should NOT be ended after releasing last claim"


class TestClaimReleaseOverride:
    """Tests for the human-only claim-release override."""

    def test_claim_release_releases_targeted_claim(self, session_offer_db):
        db_path = session_offer_db["db_path"]
        sid = "claim-release-test"

        conn = connect_test_db(db_path)
        conn.execute(
            "INSERT INTO harness_sessions (session_id, executor, provider, model, "
            "execution_lane, workspace, mode, offered_at, last_heartbeat) "
            "VALUES (%s, 'codex', 'openai', 'gpt-5.4', 'primary', %s, 'polish', "
            "'2026-04-20T00:00:00Z', '2026-04-20T00:00:00Z')",
            (sid, session_offer_db["tmp_dir"]),
        )
        conn.execute(
            "INSERT INTO work_claims (session_id, target_kind, item_id, claim_type, claimed_at, "
            "last_heartbeat) VALUES (%s, 'item', 10, 'exclusive', "
            "'2026-04-20T00:00:00Z', '2026-04-20T00:00:00Z')",
            (sid,),
        )
        conn.commit()
        conn.close()

        result = _run_client(
            ["claim-release", "--item", "YOK-10", "--reason", "operator cleanup"],
            db_path=db_path,
        )
        assert result.returncode == 0, f"stderr: {result.stderr}"

        out = json.loads(result.stdout)
        assert out["success"] is True
        assert out["item_id"] == "10"  # operator override emits normalized text id
        assert out["session_id"] == sid

        conn = connect_test_db(db_path)
        row = conn.execute(
            "SELECT released_at, release_reason FROM work_claims "
            "WHERE session_id = %s AND item_id = 10",
            (sid,),
        ).fetchone()
        conn.close()
        assert row is not None
        assert row[0] is not None
        assert row[1] == "released"

    def test_claim_release_rejects_hook_context(self, session_offer_db):
        db_path = session_offer_db["db_path"]
        sid = "claim-release-hook-context"

        conn = connect_test_db(db_path)
        conn.execute(
            "INSERT INTO harness_sessions (session_id, executor, provider, model, "
            "execution_lane, workspace, mode, offered_at, last_heartbeat) "
            "VALUES (%s, 'codex', 'openai', 'gpt-5.4', 'primary', %s, 'polish', "
            "'2026-04-20T00:00:00Z', '2026-04-20T00:00:00Z')",
            (sid, session_offer_db["tmp_dir"]),
        )
        conn.execute(
            "INSERT INTO work_claims (session_id, target_kind, item_id, claim_type, claimed_at, "
            "last_heartbeat) VALUES (%s, 'item', 10, 'exclusive', "
            "'2026-04-20T00:00:00Z', '2026-04-20T00:00:00Z')",
            (sid,),
        )
        conn.commit()
        conn.close()

        with pytest.MonkeyPatch.context() as mp:
            mp.setenv("YOKE_HOOK_EVENT", "SessionEnd")
            result = _run_client(
                ["claim-release", "--item", "YOK-10", "--reason", "bad hook use"],
                db_path=db_path,
            )
        assert result.returncode == 1
        out = json.loads(result.stdout)
        assert out["success"] is False
        assert out["code"] == "HOOK_CONTEXT"


class TestReleaseCommandsInDict:
    """release-work-claim and release-all-claims in COMMANDS; release-epic-claim removed."""

    def test_release_item_claim_in_commands(self):
        result = _run_client(["help"])
        assert result.returncode == 0
        assert "release-work-claim" in result.stdout

    def test_release_epic_claim_not_in_commands(self):
        """release-epic-claim was removed."""
        result = _run_client(["help"])
        assert result.returncode == 0
        assert "release-epic-claim" not in result.stdout

    def test_release_all_claims_in_commands(self):
        result = _run_client(["help"])
        assert result.returncode == 0
        assert "release-all-claims" in result.stdout
