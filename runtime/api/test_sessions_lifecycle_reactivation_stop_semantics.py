"""AC-7 / AC-9: Stop is a turn-boundary cleanup, reactivation is expected.

Proves the four semantic branches of the Stop cleanup contract:
1. No-claim sessions end fast (``status=ended``).
2. Active claims block cleanup (``status=has_claims``).
3. Chainable checkpoints defer cleanup (``status=chain_pending``).
4. Ended Codex sessions can reactivate on the next ``UserPromptSubmit``
   and the same ``session_id`` clears its ``ended_at`` stamp — the
   destructive-guard docstring corrected in this slice now matches the
   live behavior.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

from runtime.api.fixtures.file_test_db import connect_test_db
from yoke_core.domain.sessions import end_session_if_empty
from yoke_core.domain.sessions_lifecycle_registry import register_session
from runtime.api.test_service_client_sessions_helpers import session_offer_db  # noqa: F401


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _insert_session(
    db_path: str, session_id: str, workspace: str,
    *, claim_item: int | None = None,
    chain_checkpoint: dict | None = None,
) -> None:
    conn = connect_test_db(db_path)
    try:
        now = _now_iso()
        envelope = json.dumps({"chain_checkpoint": chain_checkpoint}) if chain_checkpoint else None
        conn.execute(
            """INSERT INTO harness_sessions
               (session_id, executor, provider, model, execution_lane,
                workspace, project_id, mode, offered_at, last_heartbeat, ended_at,
                offer_envelope)
               VALUES (%s, 'codex', 'openai', 'gpt-5.4', 'primary',
                       %s, 1, 'charge', %s, %s, NULL, %s)""",
            (session_id, workspace, now, now, envelope),
        )
        if claim_item is not None:
            conn.execute(
                """INSERT INTO work_claims
                   (session_id, target_kind, item_id, claim_type,
                    claimed_at, last_heartbeat)
                   VALUES (%s, 'item', %s, 'exclusive', %s, %s)""",
                (session_id, claim_item, now, now),
            )
        conn.commit()
    finally:
        conn.close()


def _ended_at(db_path: str, session_id: str) -> str | None:
    conn = connect_test_db(db_path)
    try:
        row = conn.execute(
            "SELECT ended_at FROM harness_sessions WHERE session_id = %s",
            (session_id,),
        ).fetchone()
        return row[0] if row else None
    finally:
        conn.close()


class TestStopSemanticsBranches:
    def test_no_claim_session_ends(self, session_offer_db) -> None:
        db = session_offer_db["db_path"]
        _insert_session(db, "sess-clean", session_offer_db["tmp_dir"])
        conn = connect_test_db(db)
        try:
            result = end_session_if_empty(conn, "sess-clean")
        finally:
            conn.close()
        assert result["status"] == "ended"
        assert result["ended"] is True
        assert _ended_at(db, "sess-clean") is not None

    def test_active_claim_blocks_with_has_claims(self, session_offer_db) -> None:
        db = session_offer_db["db_path"]
        _insert_session(
            db, "sess-busy", session_offer_db["tmp_dir"], claim_item=9001,
        )
        conn = connect_test_db(db)
        try:
            result = end_session_if_empty(conn, "sess-busy")
        finally:
            conn.close()
        assert result["status"] == "has_claims"
        assert result["ended"] is False
        assert result["active_claim_count"] == 1
        assert _ended_at(db, "sess-busy") is None

    def test_chain_pending_when_chainable_budget_remains(
        self, session_offer_db,
    ) -> None:
        db = session_offer_db["db_path"]
        _insert_session(
            db, "sess-chain", session_offer_db["tmp_dir"],
            chain_checkpoint={
                "step": 1, "max_chain_steps": 3, "action": "charge",
                "chainable": True, "handler_outcome": "completed",
                "item_id": "YOK-1234", "status": "implementing",
                "required_path": "advance",
                "pre_status": "refined-idea",
                "completed_at": _now_iso(),
            },
        )
        conn = connect_test_db(db)
        try:
            result = end_session_if_empty(conn, "sess-chain")
        finally:
            conn.close()
        assert result["status"] == "chain_pending"
        assert result["ended"] is False
        assert _ended_at(db, "sess-chain") is None


class TestReactivationAfterStop:
    """AC-7: same stable session_id may reactivate after Stop ended it."""

    def test_register_session_clears_ended_at(self, session_offer_db) -> None:
        db = session_offer_db["db_path"]
        workspace = session_offer_db["tmp_dir"]
        _insert_session(db, "sess-resume", workspace)
        # First: end the session via the Stop cleanup path.
        conn = connect_test_db(db)
        try:
            end_result = end_session_if_empty(conn, "sess-resume")
        finally:
            conn.close()
        assert end_result["status"] == "ended"
        ended_after_stop = _ended_at(db, "sess-resume")
        assert ended_after_stop is not None

        # Then: a fresh UserPromptSubmit re-registers under the same id.
        conn = connect_test_db(db)
        try:
            session = register_session(
                conn,
                session_id="sess-resume",
                executor="codex",
                provider="openai",
                model="gpt-5.4",
                execution_lane="primary",
                workspace=workspace,
                project_id=1,
                mode="wait",
            )
        finally:
            conn.close()
        # Reactivation must clear the terminal stamp — the next turn
        # treats the session as live again under the same stable id.
        assert session["ended_at"] is None
        assert _ended_at(db, "sess-resume") is None
        # Executor stays canonical across reactivation.
        assert session["executor"] in {"codex", "codex-cli"}

    def test_reactivation_is_not_a_failed_end(self, session_offer_db) -> None:
        """The fact that a session re-registered later doesn't invalidate
        the prior ``ended`` outcome — they're independent lifecycle events.
        """
        db = session_offer_db["db_path"]
        workspace = session_offer_db["tmp_dir"]
        _insert_session(db, "sess-cycle", workspace)
        conn = connect_test_db(db)
        try:
            first = end_session_if_empty(conn, "sess-cycle")
        finally:
            conn.close()
        assert first["status"] == "ended"

        conn = connect_test_db(db)
        try:
            register_session(
                conn,
                session_id="sess-cycle",
                executor="codex",
                provider="openai",
                model="gpt-5.4",
                execution_lane="primary",
                workspace=workspace,
                project_id=1,
                mode="wait",
            )
        finally:
            conn.close()

        # Stop again — should end again cleanly. No "this session is
        # already ended" surprise from the prior cycle.
        conn = connect_test_db(db)
        try:
            second = end_session_if_empty(conn, "sess-cycle")
        finally:
            conn.close()
        assert second["status"] == "ended"
