"""Read-time steering scope for fleet roster sessions."""

from __future__ import annotations

from datetime import datetime, timezone
import sqlite3

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
            actor_id INTEGER,
            current_item_id INTEGER,
            last_heartbeat TEXT,
            last_tool_call_at TEXT,
            ended_at TEXT,
            terminated_at TEXT,
            executor TEXT
        );
        CREATE TABLE items (
            id INTEGER PRIMARY KEY,
            project_id INTEGER
        );
        CREATE TABLE item_strategy_docs (
            item_id INTEGER PRIMARY KEY,
            project_id INTEGER,
            strategy_doc_slug TEXT
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
            registered_at TEXT,
            released_at TEXT
        );
        """
    )
    conn.execute("INSERT INTO projects VALUES (10, 'yoke')")
    for session_id in ("holder-1", "operator-1", "worker-1"):
        conn.execute(
            "INSERT INTO harness_sessions "
            "(session_id, project_id, last_heartbeat, last_tool_call_at, "
            "ended_at, terminated_at, executor) VALUES (?,?,?,?,?,?,?)",
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
        "INSERT INTO strategy_doc_claims VALUES "
        "(10,'MISSION','session','holder-1','2026-08-26T11:00:00Z',NULL)"
    )
    return conn


def _rows() -> list[dict[str, object]]:
    return [
        {"session_id": session_id, "project_id": 10, "project": "yoke"}
        for session_id in ("holder-1", "operator-1", "worker-1")
    ]


def test_only_the_holding_session_projects_steering_scope() -> None:
    conn = _connection()

    facts = steering_visibility(conn, _rows(), now=NOW)

    scope = facts["holder-1"]["steering_scope"]
    assert scope["project"] == "yoke"
    assert scope["strategy_docs"] == ["MISSION"]
    assert scope["liveness"] == "active"
    assert facts["operator-1"]["steering_scope"] is None
    assert facts["worker-1"]["steering_scope"] is None
    assert facts["holder-1"]["steering_group_session_id"] == "holder-1"
    assert facts["operator-1"]["steering_group_session_id"] is None
    assert facts["worker-1"]["steering_group_session_id"] is None
    assert set(facts["holder-1"]) == {"steering_scope", "steering_group_session_id"}


def test_a_worker_holding_a_covered_item_associates_to_the_seat() -> None:
    conn = _connection()
    conn.execute("INSERT INTO items VALUES (42, 10)")
    conn.execute(
        "UPDATE harness_sessions SET current_item_id = 42 "
        "WHERE session_id = 'worker-1'"
    )

    facts = steering_visibility(conn, _rows(), now=NOW)

    assert facts["worker-1"]["steering_group_session_id"] == "holder-1"
    assert facts["operator-1"]["steering_group_session_id"] is None


def test_a_worker_on_another_document_is_not_the_project_seat() -> None:
    conn = _connection()
    conn.execute("INSERT INTO items VALUES (42, 10)")
    conn.execute(
        "INSERT INTO item_strategy_docs VALUES (42, 10, 'AREA-PLAN')"
    )
    conn.execute(
        "UPDATE harness_sessions SET current_item_id = 42 "
        "WHERE session_id = 'worker-1'"
    )

    facts = steering_visibility(conn, _rows(), now=NOW)

    assert facts["worker-1"]["steering_group_session_id"] is None


def test_roster_schema_without_item_columns_still_projects_the_seat() -> None:
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
        INSERT INTO projects VALUES (10, 'yoke');
        INSERT INTO harness_sessions VALUES
            ('holder-1', 10, '2026-08-26T12:00:00Z', NULL, NULL, NULL, 'codex');
        """
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

    facts = steering_visibility(
        conn,
        [{"session_id": "holder-1", "project_id": 10, "project": "yoke"}],
        now=NOW,
    )

    assert facts["holder-1"]["steering_group_session_id"] == "holder-1"
