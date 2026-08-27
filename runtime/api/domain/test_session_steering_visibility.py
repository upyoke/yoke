"""Read-time steering context for fleet roster sessions."""

from __future__ import annotations

from datetime import datetime, timezone
import sqlite3

from yoke_contracts.session_control.launch_origin import (
    LAUNCH_ORIGIN_STEERING_BACKSTOP,
)
from yoke_contracts.turn_end_evidence import steering_report_idempotency_key
from yoke_core.domain.sessions_steering_visibility import steering_visibility
from yoke_core.domain.work_claim_targets import make_steering_target


NOW = datetime(2026, 8, 26, 12, 5, tzinfo=timezone.utc)


def _connection() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(
        """
        CREATE TABLE projects (id INTEGER PRIMARY KEY, slug TEXT);
        CREATE TABLE harness_sessions (
            session_id TEXT PRIMARY KEY,
            project_id INTEGER,
            last_heartbeat TEXT,
            last_tool_call_at TEXT,
            ended_at TEXT,
            terminated_at TEXT,
            executor TEXT
        );
        CREATE TABLE work_claims (
            id INTEGER PRIMARY KEY,
            session_id TEXT,
            target_kind TEXT,
            scope TEXT,
            claimed_at TEXT,
            released_at TEXT
        );
        CREATE TABLE strategy_doc_claims (
            project_id INTEGER,
            strategy_doc_slug TEXT,
            owner_kind TEXT,
            owner_session_id TEXT,
            released_at TEXT
        );
        CREATE TABLE session_launches (
            launch_id TEXT PRIMARY KEY,
            requester_session_id TEXT,
            project_id INTEGER,
            origin TEXT
        );
        CREATE TABLE session_launch_attempts (
            launch_id TEXT,
            native_session_id TEXT,
            started_at TEXT,
            attempt_number INTEGER
        );
        CREATE TABLE session_messages (
            message_id TEXT PRIMARY KEY,
            sender_session_id TEXT,
            idempotency_key TEXT,
            created_at TEXT
        );
        CREATE TABLE session_message_recipients (
            message_id TEXT,
            session_id TEXT,
            state TEXT,
            acknowledged_at TEXT
        );
        """
    )
    conn.execute("INSERT INTO projects VALUES (10, 'yoke')")
    for session_id in ("holder-1", "operator-1", "worker-1"):
        conn.execute(
            "INSERT INTO harness_sessions VALUES (?,?,?,?,?,?,?)",
            (
                session_id,
                10,
                "2026-08-26T12:00:00Z",
                None,
                None,
                None,
                "codex",
            ),
        )
    conn.execute(
        "INSERT INTO work_claims VALUES (1,?,?,?,?,NULL)",
        (
            "holder-1",
            "steering",
            make_steering_target(10).scope_json(),
            "2026-08-26T11:00:00Z",
        ),
    )
    conn.execute(
        "INSERT INTO strategy_doc_claims VALUES (10,'MISSION','session','holder-1',NULL)"
    )
    conn.execute(
        "INSERT INTO session_launches VALUES (?,?,?,?)",
        ("launch-1", "holder-1", 10, LAUNCH_ORIGIN_STEERING_BACKSTOP),
    )
    conn.execute(
        "INSERT INTO session_launch_attempts VALUES (?,?,?,?)",
        ("launch-1", "worker-1", "2026-08-26T11:30:00Z", 1),
    )
    conn.execute(
        "INSERT INTO session_messages VALUES (?,?,?,?)",
        (
            "message-1",
            "operator-1",
            steering_report_idempotency_key("operator-1", "fingerprint"),
            "2026-08-26T12:02:00Z",
        ),
    )
    conn.execute(
        "INSERT INTO session_message_recipients VALUES (?,?,?,?)",
        ("message-1", "holder-1", "pending", None),
    )
    return conn


def _rows() -> list[dict[str, object]]:
    return [
        {"session_id": session_id, "project_id": 10, "project": "yoke"}
        for session_id in ("holder-1", "operator-1", "worker-1")
    ]


def test_projects_scope_coverage_worker_provenance_and_report_custody() -> None:
    conn = _connection()

    facts = steering_visibility(conn, _rows(), now=NOW)

    scope = facts["holder-1"]["steering_scope"]
    assert scope["project"] == "yoke"
    assert scope["strategy_docs"] == ["MISSION"]
    assert scope["liveness"] == "active"
    assert facts["operator-1"]["steering_coverage"]["holder_session_id"] == "holder-1"
    assert facts["worker-1"]["steering_coverage"] is None
    assert facts["worker-1"]["steering_parent"] == {
        "session_id": "holder-1",
        "project_id": 10,
        "project": "yoke",
        "launch_id": "launch-1",
    }
    assert facts["operator-1"]["steering_report"]["recipient_state"] == "pending"


def test_report_custody_is_derived_from_the_recipient_receipt() -> None:
    conn = _connection()
    conn.execute(
        "UPDATE session_message_recipients SET state='acknowledged', "
        "acknowledged_at='2026-08-26T12:04:00Z' WHERE message_id='message-1'"
    )

    report = steering_visibility(conn, _rows(), now=NOW)["operator-1"][
        "steering_report"
    ]

    assert report["recipient_state"] == "acknowledged"
    assert report["acknowledged_at"] == "2026-08-26T12:04:00Z"
