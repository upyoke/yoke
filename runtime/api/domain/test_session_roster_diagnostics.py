"""Session roster message, end-blocker, and stale-TTL diagnostics."""

from __future__ import annotations

from datetime import datetime, timezone
import json
import sqlite3

from yoke_core.domain.session_control_diagnostics import session_diagnostics
from yoke_core.domain.session_control_roster import session_control_roster_result


NOW = datetime(2026, 8, 22, 12, 10, tzinfo=timezone.utc)


def _connection() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(
        """
        CREATE TABLE harness_sessions (
            session_id TEXT PRIMARY KEY,
            project_id INTEGER,
            executor_surface TEXT,
            executor_version TEXT,
            machine_id TEXT,
            last_heartbeat TEXT,
            last_tool_call_at TEXT,
            ended_at TEXT,
            terminated_at TEXT,
            turn_posture TEXT,
            turn_posture_at TEXT,
            offer_envelope TEXT
        );
        CREATE TABLE session_relays (
            relay_id TEXT PRIMARY KEY,
            machine_id TEXT,
            hostname TEXT,
            connected_until TEXT,
            state TEXT,
            surface_versions TEXT,
            project_checkouts TEXT
        );
        CREATE TABLE work_claims (
            id INTEGER PRIMARY KEY,
            session_id TEXT,
            target_kind TEXT,
            scope TEXT,
            claimed_at TEXT,
            released_at TEXT
        );
        CREATE TABLE epic_tasks (
            epic_id INTEGER,
            task_num INTEGER,
            item_worktree_id INTEGER
        );
        CREATE TABLE item_worktrees (
            id INTEGER PRIMARY KEY,
            item_id INTEGER,
            path TEXT,
            branch TEXT,
            state TEXT,
            lane_role TEXT
        );
        CREATE TABLE session_message_attempts (
            attempt_id TEXT PRIMARY KEY,
            target_session_id TEXT,
            result_code TEXT,
            started_at TEXT,
            completed_at TEXT
        );
        CREATE TABLE session_message_recipients (
            message_id TEXT,
            session_id TEXT,
            state TEXT,
            created_at TEXT,
            wake_attempt_count INTEGER
        );
        CREATE TABLE strategy_doc_claims (
            owner_kind TEXT,
            owner_session_id TEXT,
            released_at TEXT
        );
        """
    )
    return conn


def _add_session(
    conn: sqlite3.Connection,
    session_id: str,
    *,
    envelope: dict | None = None,
) -> None:
    conn.execute(
        "INSERT INTO harness_sessions VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            session_id,
            1,
            "codex-cli",
            "0.149.0",
            "machine-1",
            "2026-08-22T12:00:00Z",
            "2026-08-22T12:00:00Z",
            None,
            None,
            "waiting",
            "2026-08-22T12:00:00Z",
            json.dumps(envelope) if envelope else None,
        ),
    )


def _row(session_id: str, *, claims: list | None = None) -> dict:
    return {
        "session_id": session_id,
        "project": "yoke",
        "claims": claims or [],
        "executor": "codex",
        "executor_surface": "codex-cli",
        "liveness": "active",
        "activity_at": "2026-08-22T12:00:00Z",
    }


def test_roster_projects_latest_message_blockers_and_effective_ttl() -> None:
    conn = _connection()
    _add_session(conn, "claim-session")
    _add_session(
        conn,
        "chain-session",
        envelope={
            "max_chain_steps": 3,
            "chain_checkpoint": {
                "step": 2,
                "chainable": True,
                "handler_outcome": "completed",
                "action": "charge",
                "item_id": 2497,
            },
        },
    )
    _add_session(conn, "lock-session")
    conn.executemany(
        "INSERT INTO session_message_recipients VALUES (?,?,?,?,?)",
        (
            (
                "message-old",
                "claim-session",
                "acknowledged",
                "2026-08-22T11:00:00Z",
                1,
            ),
            (
                "message-new",
                "claim-session",
                "pending",
                "2026-08-22T12:05:00Z",
                0,
            ),
        ),
    )
    conn.execute(
        "INSERT INTO strategy_doc_claims VALUES ('session','lock-session',NULL)"
    )
    rows = [
        _row("claim-session", claims=[{"target": "YOK-2497"}]),
        _row("chain-session"),
        _row("lock-session"),
    ]

    result = session_control_roster_result(rows, conn=conn, now=NOW)
    by_session = {row["session_id"]: row for row in result["rows"]}

    message = by_session["claim-session"]["latest_message"]
    assert message == {
        "message_id": "message-new",
        "state": "pending",
        "created_at": "2026-08-22T12:05:00Z",
        "wake_attempt_count": 0,
    }
    assert by_session["claim-session"]["end_blocker"] == {
        "status": "has_claims",
        "active_claim_count": 1,
    }
    assert by_session["chain-session"]["end_blocker"]["status"] == "chain_pending"
    assert by_session["chain-session"]["end_blocker"]["checkpoint_step"] == 2
    assert by_session["chain-session"]["end_blocker"]["max_chain_steps"] == 3
    assert by_session["lock-session"]["end_blocker"] == {
        "status": "has_document_locks",
        "active_claim_count": 0,
        "active_document_lock_count": 1,
    }
    assert by_session["claim-session"]["effective_stale_ttl_minutes"] == 60
    assert by_session["claim-session"]["stale_eligible_at"] == ("2026-08-22T13:00:00Z")


def test_terminated_session_has_no_end_or_stale_diagnostic() -> None:
    conn = _connection()
    row = _row("terminated-session")
    row["liveness"] = "terminated"
    projected = session_diagnostics(
        conn,
        [row],
        {
            "terminated-session": {
                "terminated_at": "2026-08-22T12:05:00Z",
                "offer_envelope": json.dumps(
                    {
                        "max_chain_steps": 3,
                        "chain_checkpoint": {
                            "step": 2,
                            "chainable": True,
                            "handler_outcome": "completed",
                        },
                    }
                ),
            }
        },
    )["terminated-session"]

    assert projected["end_blocker"] is None
    assert projected["stale_eligible_at"] is None
