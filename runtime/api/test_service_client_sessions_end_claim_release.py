"""CLI regression for session-end no-flags auto-release payloads.

Covers the released_claims surface on the ``session-end`` command for
single-claim, multi-claim, and epic-task-claim sessions. Kept separate
from ``test_service_client_sessions_end_command.py`` so that file stays
under its 350-line cap.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

from runtime.api.fixtures.file_test_db import connect_test_db
from runtime.api.test_service_client import _run_client
from runtime.api.test_service_client_sessions_helpers import (
    session_offer_db,  # noqa: F401
    _pre_register_session,
)


_FRESH_TS = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _insert_item_claim(conn, session_id: str, item_id: int) -> None:
    conn.execute(
        """INSERT INTO work_claims
           (session_id, target_kind, item_id, claim_type, claimed_at, last_heartbeat)
           VALUES (%s, 'item', %s, 'exclusive', %s, %s)""",
        (session_id, item_id, _FRESH_TS, _FRESH_TS),
    )


def _insert_epic_task_claim(
    conn, session_id: str, epic_id: int, task_num: int,
) -> None:
    conn.execute(
        """INSERT INTO work_claims
           (session_id, target_kind, epic_id, task_num,
            claim_type, claimed_at, last_heartbeat)
           VALUES (%s, 'epic_task', %s, %s, 'exclusive', %s, %s)""",
        (session_id, epic_id, task_num, _FRESH_TS, _FRESH_TS),
    )


class TestSessionEndAutoReleasePayload:
    """released_claims payload coverage for session-end (no flags)."""

    def test_single_item_claim_payload(self, session_offer_db):
        sid = "claim-release-single"
        db = session_offer_db["db_path"]
        ws = session_offer_db["tmp_dir"]
        _pre_register_session(db, sid, workspace=ws)
        conn = connect_test_db(db)
        _insert_item_claim(conn, sid, 301)
        conn.commit()
        conn.close()

        result = _run_client(
            ["session-end", "--session-id", sid], db_path=db,
        )
        assert result.returncode == 0, f"stderr: {result.stderr}"
        data = json.loads(result.stdout)
        assert data["success"] is True
        assert data["released_claims"] == [
            {
                "target_kind": "item",
                "item_id": 301,
                "claim_id": data["released_claims"][0]["claim_id"],
            }
        ]
        assert data["session"]["ended_at"] is not None

    def test_multiple_item_claims_payload(self, session_offer_db):
        sid = "claim-release-multi"
        db = session_offer_db["db_path"]
        ws = session_offer_db["tmp_dir"]
        _pre_register_session(db, sid, workspace=ws)
        conn = connect_test_db(db)
        _insert_item_claim(conn, sid, 401)
        _insert_item_claim(conn, sid, 402)
        _insert_item_claim(conn, sid, 403)
        conn.commit()
        conn.close()

        result = _run_client(
            ["session-end", "--session-id", sid], db_path=db,
        )
        assert result.returncode == 0, f"stderr: {result.stderr}"
        data = json.loads(result.stdout)
        assert len(data["released_claims"]) == 3
        item_ids = sorted(entry["item_id"] for entry in data["released_claims"])
        assert item_ids == [401, 402, 403]
        for entry in data["released_claims"]:
            assert entry["target_kind"] == "item"
            assert "claim_id" in entry

    def test_epic_task_claim_payload(self, session_offer_db):
        """AC-12: epic_task targets surface epic_id + task_num, not item_id."""
        sid = "claim-release-epic-task"
        db = session_offer_db["db_path"]
        ws = session_offer_db["tmp_dir"]
        _pre_register_session(db, sid, workspace=ws)
        conn = connect_test_db(db)
        _insert_epic_task_claim(conn, sid, epic_id=5000, task_num=7)
        conn.commit()
        conn.close()

        result = _run_client(
            ["session-end", "--session-id", sid], db_path=db,
        )
        assert result.returncode == 0, f"stderr: {result.stderr}"
        data = json.loads(result.stdout)
        assert len(data["released_claims"]) == 1
        entry = data["released_claims"][0]
        assert entry["target_kind"] == "epic_task"
        assert entry["epic_id"] == 5000
        assert entry["task_num"] == 7
        assert "item_id" not in entry
        assert "claim_id" in entry

    def test_mixed_targets_each_payload_kind_correct(self, session_offer_db):
        sid = "claim-release-mixed"
        db = session_offer_db["db_path"]
        ws = session_offer_db["tmp_dir"]
        _pre_register_session(db, sid, workspace=ws)
        conn = connect_test_db(db)
        _insert_item_claim(conn, sid, 901)
        _insert_epic_task_claim(conn, sid, epic_id=6000, task_num=2)
        conn.commit()
        conn.close()

        result = _run_client(
            ["session-end", "--session-id", sid], db_path=db,
        )
        assert result.returncode == 0, f"stderr: {result.stderr}"
        data = json.loads(result.stdout)
        assert len(data["released_claims"]) == 2

        item_entries = [
            e for e in data["released_claims"] if e["target_kind"] == "item"
        ]
        task_entries = [
            e for e in data["released_claims"]
            if e["target_kind"] == "epic_task"
        ]
        assert len(item_entries) == 1
        assert item_entries[0]["item_id"] == 901
        assert len(task_entries) == 1
        assert task_entries[0]["epic_id"] == 6000
        assert task_entries[0]["task_num"] == 2

    def test_no_claims_omits_released_claims_key(self, session_offer_db):
        sid = "claim-release-empty"
        db = session_offer_db["db_path"]
        ws = session_offer_db["tmp_dir"]
        _pre_register_session(db, sid, workspace=ws)

        result = _run_client(
            ["session-end", "--session-id", sid], db_path=db,
        )
        assert result.returncode == 0, f"stderr: {result.stderr}"
        data = json.loads(result.stdout)
        assert data["success"] is True
        assert "released_claims" not in data
