"""Tests for service_client release-work-claim command."""

from __future__ import annotations

import json

from runtime.api.fixtures.file_test_db import connect_test_db
from runtime.api.test_service_client import _run_client
from runtime.api.test_service_client_sessions_helpers import session_offer_db  # noqa: F401


def _sun(item_id: int) -> str:
    return f"YOK-{item_id}"


class TestReleaseItemClaim:
    """Tests for release-work-claim command."""

    def test_release_item_claim_active_claim(self, session_offer_db):
        """AC-1: release-work-claim releases an active item claim."""
        db_path = session_offer_db["db_path"]
        sid = "release-item-test"
        item_id = 99
        item_ref = _sun(item_id)

        # Create an active session and claim
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
            "last_heartbeat) VALUES (%s, 'item', %s, 'exclusive', "
            "'2026-04-20T00:00:00Z', '2026-04-20T00:00:00Z')",
            (sid, item_id),
        )
        conn.commit()
        conn.close()

        result = _run_client(
            ["release-work-claim", "--session-id", sid,
             "--item", item_ref, "--reason", "completed"],
            db_path=db_path,
        )
        assert result.returncode == 0, f"stderr: {result.stderr}"

        out = json.loads(result.stdout)
        assert out["success"] is True
        assert "claim_id" in out
        # caller intent is preserved in reason_intent and canonical
        # enum value is stored in reason_stored.
        assert out["reason_intent"] == "completed"
        assert out["reason_stored"] == "completed"

        # Verify the claim is released with the canonical enum value
        conn = connect_test_db(db_path)
        row = conn.execute(
            "SELECT released_at, release_reason FROM work_claims "
            "WHERE session_id = %s AND target_kind='item' AND item_id = %s",
            (sid, item_id),
        ).fetchone()
        conn.close()
        assert row is not None
        assert row[0] is not None  # released_at is set
        assert row[1] == "completed"

    def test_release_item_claim_normalizes_bare_numeric_id(self, session_offer_db):
        """Bare numeric release requests match canonical bare-numeric claim storage."""
        db_path = session_offer_db["db_path"]
        sid = "release-bare-numeric-test"

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
            "last_heartbeat) VALUES (%s, 'item', 99, 'exclusive', "
            "'2026-04-20T00:00:00Z', '2026-04-20T00:00:00Z')",
            (sid,),
        )
        conn.commit()
        conn.close()

        result = _run_client(
            ["release-work-claim", "--session-id", sid,
             "--item", "0099", "--reason", "completed"],
            db_path=db_path,
        )
        assert result.returncode == 0, f"stderr: {result.stderr}"

        conn = connect_test_db(db_path)
        row = conn.execute(
            "SELECT released_at, release_reason FROM work_claims "
            "WHERE session_id = %s AND target_kind='item' AND item_id = 99",
            (sid,),
        ).fetchone()
        conn.close()
        assert row is not None
        assert row[0] is not None
        assert row[1] == "completed"

    def test_release_process_claim_by_key(self, session_offer_db):
        """Process targets release through --process KEY rather than --item.

        Replaces the legacy "sentinel claim" test: STRATEGIZE/FEED are now
        first-class process targets in the typed-target world, not pseudo-items.
        """
        db_path = session_offer_db["db_path"]
        sid = "release-process-test"

        conn = connect_test_db(db_path)
        conn.execute(
            "INSERT INTO harness_sessions (session_id, executor, provider, model, "
            "execution_lane, workspace, mode, offered_at, last_heartbeat) "
            "VALUES (%s, 'claude-code', 'anthropic', 'opus', 'primary', %s, 'hook', "
            "'2026-04-20T00:00:00Z', '2026-04-20T00:00:00Z')",
            (sid, session_offer_db["tmp_dir"]),
        )
        conn.execute(
            "INSERT INTO work_claims (session_id, target_kind, process_key, "
            "conflict_group, claim_type, claimed_at, last_heartbeat) "
            "VALUES (%s, 'process', 'STRATEGIZE', 'strategy-control-plane:yoke', "
            "'exclusive', '2026-04-20T00:00:00Z', '2026-04-20T00:00:00Z')",
            (sid,),
        )
        conn.commit()
        conn.close()

        result = _run_client(
            ["release-work-claim", "--session-id", sid,
             "--process", "STRATEGIZE", "--project", "yoke",
             "--reason", "completed"],
            db_path=db_path,
        )
        assert result.returncode == 0, f"stderr: {result.stderr}"

        conn = connect_test_db(db_path)
        row = conn.execute(
            "SELECT released_at, release_reason FROM work_claims "
            "WHERE session_id = %s AND target_kind='process' AND process_key = 'STRATEGIZE'",
            (sid,),
        ).fetchone()
        conn.close()
        assert row is not None
        assert row[0] is not None
        assert row[1] == "completed"

    def test_release_item_claim_missing_claim(self, session_offer_db):
        """No active claim returns a distinct exit code and warning."""
        db_path = session_offer_db["db_path"]
        sid = "release-noop-test"
        item_ref = _sun(99)

        # Create an active session but no claim
        conn = connect_test_db(db_path)
        conn.execute(
            "INSERT INTO harness_sessions (session_id, executor, provider, model, "
            "execution_lane, workspace, mode, offered_at, last_heartbeat) "
            "VALUES (%s, 'claude-code', 'anthropic', 'opus', 'primary', %s, 'hook', "
            "'2026-04-20T00:00:00Z', '2026-04-20T00:00:00Z')",
            (sid, session_offer_db["tmp_dir"]),
        )
        conn.commit()
        conn.close()

        result = _run_client(
            ["release-work-claim", "--session-id", sid,
             "--item", item_ref, "--reason", "cleanup"],
            db_path=db_path,
        )
        # This requested item has never had a claim row in this fixture.
        assert result.returncode == 5
        out = json.loads(result.stdout)
        assert out["success"] is False
        assert out["released"] is False
        assert out["failure_reason"] == "item_not_found"
        assert "claim release failed" in result.stderr
        assert "item_not_found" in result.stderr

    def test_release_item_claim_not_owned_names_holder(self, session_offer_db):
        """Cross-session release returns NOT_OWNED and names the holder."""
        db_path = session_offer_db["db_path"]
        owner_sid = "release-owner"
        caller_sid = "release-caller"
        item_ref = _sun(99)

        conn = connect_test_db(db_path)
        for sid in (owner_sid, caller_sid):
            conn.execute(
                "INSERT INTO harness_sessions (session_id, executor, provider, model, "
                "execution_lane, workspace, mode, offered_at, last_heartbeat) "
                "VALUES (%s, 'claude-code', 'anthropic', 'opus', 'primary', %s, 'hook', "
                "'2026-04-20T00:00:00Z', '2026-04-20T00:00:00Z')",
                (sid, session_offer_db["tmp_dir"]),
            )
        conn.execute(
            "INSERT INTO work_claims (session_id, target_kind, item_id, claim_type, claimed_at, "
            "last_heartbeat) VALUES (%s, 'item', 99, 'exclusive', "
            "'2026-04-20T00:00:00Z', '2026-04-20T00:00:00Z')",
            (owner_sid,),
        )
        conn.commit()
        conn.close()

        result = _run_client(
            ["release-work-claim", "--session-id", caller_sid,
             "--item", item_ref, "--reason", "handoff-to-polish"],
            db_path=db_path,
        )

        assert result.returncode == 3
        out = json.loads(result.stdout)
        assert out["success"] is False
        assert out["failure_reason"] == "not_owned"
        assert out["holder_session_id"] == owner_sid
        assert owner_sid in result.stderr

    def test_release_item_claim_already_terminal_exit_code(self, session_offer_db):
        """Released historical claims return ALREADY_TERMINAL."""
        db_path = session_offer_db["db_path"]
        sid = "release-terminal-test"
        item_ref = _sun(99)

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
            "last_heartbeat, released_at, release_reason) "
            "VALUES (%s, 'item', 99, 'exclusive', '2026-04-20T00:00:00Z', "
            "'2026-04-20T00:00:00Z', '2026-04-20T00:01:00Z', 'released')",
            (sid,),
        )
        conn.commit()
        conn.close()

        result = _run_client(
            ["release-work-claim", "--session-id", sid,
             "--item", item_ref, "--reason", "finalize-exit"],
            db_path=db_path,
        )

        assert result.returncode == 4
        out = json.loads(result.stdout)
        assert out["success"] is False
        assert out["failure_reason"] == "already_terminal"
        assert out["holder_session_id"] == sid

    def test_release_item_claim_completed_rejected_for_active_item_status(self, session_offer_db):
        """`completed` is rejected until the item reaches a success handoff status."""
        db_path = session_offer_db["db_path"]
        sid = "release-active-status-test"
        item_id = 99
        item_ref = _sun(item_id)

        conn = connect_test_db(db_path)
        conn.execute(
            "INSERT INTO items (id, title, status, created_at, updated_at) "
            "VALUES (99, 'Polish item', 'polishing-implementation', "
            "'2026-04-20T00:00:00Z', '2026-04-20T00:00:00Z')"
        )
        conn.execute(
            "INSERT INTO harness_sessions (session_id, executor, provider, model, "
            "execution_lane, workspace, mode, offered_at, last_heartbeat, current_item_id, current_item_set_at) "
            "VALUES (%s, 'claude-code', 'anthropic', 'opus', 'primary', %s, 'hook', "
            "'2026-04-20T00:00:00Z', '2026-04-20T00:00:00Z', '99', '2026-04-20T00:00:00Z')",
            (sid, session_offer_db["tmp_dir"]),
        )
        conn.execute(
            "INSERT INTO work_claims (session_id, target_kind, item_id, claim_type, claimed_at, "
            "last_heartbeat) VALUES (%s, 'item', 99, 'exclusive', "
            "'2026-04-20T00:00:00Z', '2026-04-20T00:00:00Z')",
            (sid,),
        )
        conn.commit()
        conn.close()

        result = _run_client(
            ["release-work-claim", "--session-id", sid,
             "--item", item_ref, "--reason", "completed"],
            db_path=db_path,
        )
        # Validation rejection now exits DOMAIN_ERROR (6), emits
        # ItemClaimReleaseFailed, and logs a single Warning line.
        assert result.returncode == 6
        assert "polishing-implementation" in result.stderr
        assert "Warning: claim release failed" in result.stderr
        assert "domain_error" in result.stderr

        conn = connect_test_db(db_path)
        row = conn.execute(
            "SELECT released_at FROM work_claims WHERE session_id = %s AND target_kind='item' AND item_id = 99",
            (sid,),
        ).fetchone()
        session_row = conn.execute(
            "SELECT current_item_id FROM harness_sessions WHERE session_id = %s",
            (sid,),
        ).fetchone()
        conn.close()
        assert row is not None
        assert row[0] is None
        assert session_row is not None
        assert session_row[0] == "99"
