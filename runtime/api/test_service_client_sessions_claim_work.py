"""Tests for service_client claim-work command."""

from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest

from runtime.api.fixtures.file_test_db import connect_test_db
from runtime.api.test_service_client import _run_client
from runtime.api.test_service_client_sessions_helpers import session_offer_db  # noqa: F401


def _fresh_ts() -> str:
    """Return a timestamp fresh enough for SQL-side stale-window checks."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class TestClaimItem:
    """Tests for claim-work command."""

    def test_claim_item_active_session_creates_claim(self, session_offer_db):
        """AC-1: claim-work with active session creates a work_claims row."""
        db_path = session_offer_db["db_path"]
        sid = "claim-test-active"

        # Create an active session
        conn = connect_test_db(db_path)
        conn.execute(
            "INSERT INTO harness_sessions (session_id, executor, provider, model, "
            "execution_lane, workspace, project_id, mode, offered_at, last_heartbeat) "
            "VALUES (%s, 'claude-code', 'anthropic', 'opus', 'primary', %s, 1, "
            "'hook', '2026-04-20T00:00:00Z', '2026-04-20T00:00:00Z')",
            (sid, session_offer_db["tmp_dir"]),
        )
        conn.commit()
        conn.close()

        result = _run_client(
            ["claim-work", "--session-id", sid, "--item", "YOK-10"],
            db_path=db_path,
        )
        assert result.returncode == 0, f"stderr: {result.stderr}"

        out = json.loads(result.stdout)
        assert out["success"] is True

        # Verify the work_claims row exists
        conn = connect_test_db(db_path)
        row = conn.execute(
            "SELECT session_id, item_id, claim_type FROM work_claims "
            "WHERE session_id = %s AND target_kind='item' AND item_id = 10 "
            "AND released_at IS NULL",
            (sid,),
        ).fetchone()
        attribution = conn.execute(
            "SELECT current_item_id FROM harness_sessions WHERE session_id = %s",
            (sid,),
        ).fetchone()
        conn.close()
        assert row is not None
        assert row[0] == sid
        assert row[1] == 10
        assert row[2] == "exclusive"
        assert attribution[0] == "10"

    def test_claim_item_normalizes_bare_numeric_id(self, session_offer_db):
        """Bare numeric item IDs are canonicalized to bare numeric at claim time."""
        db_path = session_offer_db["db_path"]
        sid = "claim-test-bare-numeric"

        conn = connect_test_db(db_path)
        conn.execute(
            "INSERT INTO harness_sessions (session_id, executor, provider, model, "
            "execution_lane, workspace, project_id, mode, offered_at, last_heartbeat) "
            "VALUES (%s, 'claude-code', 'anthropic', 'opus', 'primary', %s, 1, "
            "'hook', '2026-04-20T00:00:00Z', '2026-04-20T00:00:00Z')",
            (sid, session_offer_db["tmp_dir"]),
        )
        conn.commit()
        conn.close()

        result = _run_client(
            ["claim-work", "--session-id", sid, "--item", "0010"],
            db_path=db_path,
        )
        assert result.returncode == 0, f"stderr: {result.stderr}"

        conn = connect_test_db(db_path)
        row = conn.execute(
            "SELECT item_id FROM work_claims "
            "WHERE session_id = %s AND target_kind='item' AND released_at IS NULL",
            (sid,),
        ).fetchone()
        conn.close()
        assert row is not None
        assert row[0] == 10

    def test_claim_work_rejects_non_numeric_item_id(self, session_offer_db):
        """Process sentinels like STRATEGIZE are not items — claim-work --item rejects them.

        The pseudo-item world (item_id='STRATEGIZE') was retired with the typed-target
        cutover; STRATEGIZE/FEED are now first-class process targets reached through
        ``claim-work --process``, not ``claim-work --item``.
        """
        db_path = session_offer_db["db_path"]
        sid = "claim-test-sentinel"

        conn = connect_test_db(db_path)
        conn.execute(
            "INSERT INTO harness_sessions (session_id, executor, provider, model, "
            "execution_lane, workspace, project_id, mode, offered_at, last_heartbeat) "
            "VALUES (%s, 'claude-code', 'anthropic', 'opus', 'primary', %s, 1, "
            "'hook', '2026-04-20T00:00:00Z', '2026-04-20T00:00:00Z')",
            (sid, session_offer_db["tmp_dir"]),
        )
        conn.commit()
        conn.close()

        result = _run_client(
            ["claim-work", "--session-id", sid, "--item", "STRATEGIZE"],
            db_path=db_path,
        )
        assert result.returncode != 0, (
            f"claim-work --item should reject non-numeric ids; got stdout={result.stdout!r}"
        )

    def test_claim_item_missing_session_returns_error(self, session_offer_db):
        """AC-2: claim-work with missing session returns exit 1 with truthful error."""
        db_path = session_offer_db["db_path"]

        result = _run_client(
            ["claim-work", "--session-id", "nonexistent", "--item", "YOK-10"],
            db_path=db_path,
        )
        assert result.returncode == 1

        err = json.loads(result.stderr)
        assert err["success"] is False
        assert "no active session" in err["error"]

    def test_claim_item_ended_session_returns_error(self, session_offer_db):
        """AC-3: claim-work with ended session returns exit 1 with session-ended error."""
        db_path = session_offer_db["db_path"]
        sid = "claim-test-ended"

        # Create an ended session
        conn = connect_test_db(db_path)
        conn.execute(
            "INSERT INTO harness_sessions (session_id, executor, provider, model, "
            "execution_lane, workspace, project_id, mode, offered_at, last_heartbeat, ended_at) "
            "VALUES (%s, 'claude-code', 'anthropic', 'opus', 'primary', %s, 1, "
            "'hook', '2026-04-20T00:00:00Z', '2026-04-20T00:00:00Z', "
            "'2026-04-20T00:00:00Z')",
            (sid, session_offer_db["tmp_dir"]),
        )
        conn.commit()
        conn.close()

        result = _run_client(
            ["claim-work", "--session-id", sid, "--item", "YOK-10"],
            db_path=db_path,
        )
        assert result.returncode == 1

        err = json.loads(result.stderr)
        assert err["success"] is False
        assert "has ended" in err["error"]
        assert sid in err["error"]

    def test_claim_item_conflict_returns_error(self, session_offer_db):
        """AC-4: claim-work with conflict returns exit 1 with conflict message."""
        db_path = session_offer_db["db_path"]

        # Create two active sessions.  Owner needs a FRESH heartbeat so the
        # stale-reclaim path does not silently release the claim.
        fresh_ts = _fresh_ts()
        conn = connect_test_db(db_path)
        conn.execute(
            "INSERT INTO harness_sessions (session_id, executor, provider, model, "
            "execution_lane, workspace, project_id, mode, offered_at, last_heartbeat) "
            "VALUES ('owner-session', 'claude-code', 'anthropic', 'opus', 'primary', "
            "%s, 1, 'hook', %s, %s)",
            (session_offer_db["tmp_dir"], fresh_ts, fresh_ts),
        )
        conn.execute(
            "INSERT INTO harness_sessions (session_id, executor, provider, model, "
            "execution_lane, workspace, project_id, mode, offered_at, last_heartbeat) "
            "VALUES ('thief-session', 'claude-code', 'anthropic', 'opus', 'primary', "
            "%s, 1, 'hook', %s, %s)",
            (session_offer_db["tmp_dir"], fresh_ts, fresh_ts),
        )
        # Owner claims the item with a fresh heartbeat
        conn.execute(
            "INSERT INTO work_claims (session_id, target_kind, item_id, claim_type, claimed_at, "
            "last_heartbeat) VALUES ('owner-session', 'item', '10', 'exclusive', %s, %s)",
            (fresh_ts, fresh_ts),
        )
        conn.commit()
        conn.close()

        # Thief tries to claim the same item
        result = _run_client(
            ["claim-work", "--session-id", "thief-session", "--item", "YOK-10"],
            db_path=db_path,
        )
        assert result.returncode == 1

        err = json.loads(result.stderr)
        assert err["success"] is False
        assert "already claimed" in err["error"]


class TestClaimProcess:
    """Process-target coverage for recurring control-plane work."""

    @staticmethod
    def _register_session(db_path: str, session_id: str, workspace: str) -> None:
        fresh_ts = _fresh_ts()
        conn = connect_test_db(db_path)
        conn.execute(
            "INSERT INTO harness_sessions (session_id, executor, provider, model, "
            "execution_lane, workspace, project_id, mode, offered_at, last_heartbeat) "
            "VALUES (%s, 'claude-code', 'anthropic', 'opus', 'primary', %s, 1, 'hook', "
            "%s, %s)",
            (session_id, workspace, fresh_ts, fresh_ts),
        )
        conn.commit()
        conn.close()

    def test_claim_doctor_process_creates_process_claim(self, session_offer_db):
        db_path = session_offer_db["db_path"]
        sid = "claim-test-doctor-process"
        self._register_session(db_path, sid, session_offer_db["tmp_dir"])

        result = _run_client(
            [
                "claim-work",
                "--session-id",
                sid,
                "--process",
                "DOCTOR",
                "--project",
                "yoke",
            ],
            db_path=db_path,
        )
        assert result.returncode == 0, result.stderr

        conn = connect_test_db(db_path)
        row = conn.execute(
            "SELECT target_kind, process_key, conflict_group, item_id "
            "FROM work_claims WHERE session_id = %s AND released_at IS NULL",
            (sid,),
        ).fetchone()
        conn.close()
        assert tuple(row) == ("process", "DOCTOR", "doctor:yoke", None)

    @pytest.mark.parametrize(
        ("first_process", "second_process"),
        [
            ("STRATEGIZE", "STRATEGIZE"),
            ("FEED", "FEED"),
            ("STRATEGIZE", "FEED"),
            ("FEED", "STRATEGIZE"),
        ],
    )
    def test_strategy_control_processes_conflict_by_shared_group(
        self, session_offer_db, first_process, second_process,
    ):
        db_path = session_offer_db["db_path"]
        self._register_session(db_path, "process-owner", session_offer_db["tmp_dir"])
        self._register_session(db_path, "process-thief", session_offer_db["tmp_dir"])

        first = _run_client(
            [
                "claim-work",
                "--session-id",
                "process-owner",
                "--process",
                first_process,
                "--project",
                "yoke",
            ],
            db_path=db_path,
        )
        assert first.returncode == 0, first.stderr

        second = _run_client(
            [
                "claim-work",
                "--session-id",
                "process-thief",
                "--process",
                second_process,
                "--project",
                "yoke",
            ],
            db_path=db_path,
        )
        assert second.returncode == 1
        err = json.loads(second.stderr)
        assert err["success"] is False
        assert "already claimed" in err["error"]


class TestClaimCommandsInDict:
    """claim-work is the typed-target acquire surface; claim-epic-task is gone."""

    def test_claim_work_in_commands(self):
        result = _run_client(["help"])
        assert result.returncode == 0
        assert "claim-work" in result.stdout
        old_item_command = "claim" + "-item"
        assert old_item_command not in result.stdout

    def test_claim_epic_task_not_in_commands(self):
        """claim-epic-task was removed."""
        result = _run_client(["help"])
        assert result.returncode == 0
        assert "claim-epic-task" not in result.stdout
