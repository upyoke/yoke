"""Focused regression: ``session-end-if-empty`` returns typed Stop statuses.

Separate from ``test_service_client_sessions_end_cleanup.py`` so the
Stop-cleanup status matrix has a dedicated home.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

from runtime.api.fixtures.file_test_db import connect_test_db
from runtime.api.test_service_client import _run_client
from runtime.api.test_service_client_sessions_helpers import session_offer_db  # noqa: F401
from yoke_core.domain.work_claim_targets import make_item_target


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _insert_session(
    db_path: str,
    session_id: str,
    workspace: str,
    *,
    ended: bool = False,
) -> None:
    conn = connect_test_db(db_path)
    try:
        now = _now_iso()
        conn.execute(
            """INSERT INTO harness_sessions
               (session_id, executor, provider, model, execution_lane,
                workspace, mode, offered_at, last_heartbeat, ended_at)
               VALUES (%s, 'codex', 'openai', 'gpt-5.4', 'primary',
                       %s, 'charge', %s, %s, %s)""",
            (
                session_id,
                workspace,
                now,
                now,
                now if ended else None,
            ),
        )
        conn.commit()
    finally:
        conn.close()


def _insert_claim(db_path: str, session_id: str, item_id: int) -> None:
    conn = connect_test_db(db_path)
    try:
        now = _now_iso()
        target = make_item_target(item_id)
        conn.execute(
            """INSERT INTO work_claims
               (session_id, target_kind, scope, claim_type,
                claimed_at, last_heartbeat)
               VALUES (%s, %s, %s, 'exclusive', %s, %s)""",
            (session_id, target.kind, target.scope_json(), now, now),
        )
        conn.commit()
    finally:
        conn.close()


class TestSessionEndIfEmptyStopBudget:
    """Each branch returns a stable Stop-cleanup status."""

    def test_not_found_for_unknown_session(self, session_offer_db) -> None:
        result = _run_client(
            ["session-end-if-empty", "--session-id", "missing-sess"],
            db_path=session_offer_db["db_path"],
        )
        assert result.returncode == 0
        data = json.loads(result.stdout)
        assert data["success"] is True
        assert data["status"] == "not_found"
        assert data["ended"] is False

    def test_ended_when_no_claims(self, session_offer_db) -> None:
        db = session_offer_db["db_path"]
        _insert_session(db, "sess-ended", session_offer_db["tmp_dir"])
        result = _run_client(
            ["session-end-if-empty", "--session-id", "sess-ended"],
            db_path=db,
        )
        assert result.returncode == 0
        data = json.loads(result.stdout)
        assert data["success"] is True
        assert data["status"] == "ended"
        assert data["ended"] is True

    def test_already_ended_for_terminal_session(self, session_offer_db) -> None:
        db = session_offer_db["db_path"]
        _insert_session(db, "sess-old", session_offer_db["tmp_dir"], ended=True)
        result = _run_client(
            ["session-end-if-empty", "--session-id", "sess-old"],
            db_path=db,
        )
        assert result.returncode == 0
        data = json.loads(result.stdout)
        assert data["success"] is True
        assert data["status"] == "already_ended"
        assert data["ended"] is False

    def test_has_claims_when_session_is_busy(self, session_offer_db) -> None:
        db = session_offer_db["db_path"]
        _insert_session(db, "sess-busy", session_offer_db["tmp_dir"])
        _insert_claim(db, "sess-busy", 4242)
        result = _run_client(
            ["session-end-if-empty", "--session-id", "sess-busy"],
            db_path=db,
        )
        assert result.returncode == 0
        data = json.loads(result.stdout)
        assert data["success"] is True
        assert data["status"] == "has_claims"
        assert data["active_claim_count"] == 1
        assert data["ended"] is False
