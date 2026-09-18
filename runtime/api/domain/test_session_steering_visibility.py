"""Read-time steering scope for fleet roster sessions."""

from __future__ import annotations

from datetime import datetime, timezone
import sqlite3

from yoke_core.domain.sessions_steering_visibility import (
    _covering_group_scope,
    steering_visibility,
)
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
    # The seat leads its own group, so it carries the group scope the
    # colour resolver keys on alongside its own steering scope.
    assert set(facts["holder-1"]) == {
        "steering_scope",
        "steering_group_session_id",
        "steering_group_scope",
    }


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
    group = facts["worker-1"]["steering_group_scope"]
    assert group["scope"] == {"project_id": 10}
    assert "document" not in group["scope"]
    assert group["strategy_docs"] == []


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


def _two_document_seats(conn: sqlite3.Connection) -> None:
    conn.execute("DELETE FROM work_claims")
    conn.execute("DELETE FROM strategy_doc_claims")
    conn.execute(
        "INSERT INTO work_claims VALUES (1,?,?,?,?,NULL)",
        (
            "holder-1",
            "steering",
            make_steering_target(10, "CURRENT-PLAN").scope_json(),
            "2026-08-26T11:00:00Z",
        ),
    )
    conn.execute(
        "INSERT INTO work_claims VALUES (2,?,?,?,?,NULL)",
        (
            "holder-1",
            "steering",
            make_steering_target(10, "RELEASES").scope_json(),
            "2026-08-26T11:01:00Z",
        ),
    )
    conn.execute(
        "INSERT INTO strategy_doc_claims VALUES "
        "(10,'CURRENT-PLAN','session','holder-1','2026-08-26T11:00:00Z',NULL)"
    )
    conn.execute(
        "INSERT INTO strategy_doc_claims VALUES "
        "(10,'RELEASES','session','holder-1','2026-08-26T11:01:00Z',NULL)"
    )


def test_worker_group_scope_names_the_covering_document_claim() -> None:
    conn = _connection()
    _two_document_seats(conn)
    conn.execute("INSERT INTO items VALUES (42, 10)")
    conn.execute(
        "INSERT INTO item_strategy_docs VALUES (42, 10, 'CURRENT-PLAN')"
    )
    conn.execute(
        "UPDATE harness_sessions SET current_item_id = 42 "
        "WHERE session_id = 'worker-1'"
    )

    group = steering_visibility(conn, _rows(), now=NOW)["worker-1"][
        "steering_group_scope"
    ]

    assert group["scope"] == {"project_id": 10, "document": "CURRENT-PLAN"}
    assert group["strategy_docs"] == ["CURRENT-PLAN"]


def test_worker_on_the_later_document_does_not_inherit_the_first_claim() -> None:
    conn = _connection()
    _two_document_seats(conn)
    conn.execute("INSERT INTO items VALUES (42, 10)")
    conn.execute("INSERT INTO item_strategy_docs VALUES (42, 10, 'RELEASES')")
    conn.execute(
        "UPDATE harness_sessions SET current_item_id = 42 "
        "WHERE session_id = 'worker-1'"
    )

    group = steering_visibility(conn, _rows(), now=NOW)["worker-1"][
        "steering_group_scope"
    ]

    assert group["scope"]["document"] == "RELEASES"
    assert group["strategy_docs"] == ["RELEASES"]


def test_covering_claim_projects_when_it_is_not_the_first_project_seat() -> None:
    conn = _connection()
    conn.execute(
        "INSERT INTO harness_sessions "
        "(session_id, project_id, last_heartbeat, last_tool_call_at, "
        "ended_at, terminated_at, executor) VALUES (?,?,?,?,?,?,?)",
        (
            "holder-2",
            10,
            "2026-08-26T12:00:00Z",
            None,
            None,
            None,
            "codex",
        ),
    )
    conn.execute("DELETE FROM work_claims")
    conn.execute("DELETE FROM strategy_doc_claims")
    conn.execute(
        "INSERT INTO work_claims VALUES (1,?,?,?,?,NULL)",
        (
            "holder-1",
            "steering",
            make_steering_target(10, "CURRENT-PLAN").scope_json(),
            "2026-08-26T11:00:00Z",
        ),
    )
    conn.execute(
        "INSERT INTO work_claims VALUES (2,?,?,?,?,NULL)",
        (
            "holder-2",
            "steering",
            make_steering_target(10, "RELEASES").scope_json(),
            "2026-08-26T11:01:00Z",
        ),
    )
    conn.execute("INSERT INTO items VALUES (42, 10)")
    conn.execute("INSERT INTO item_strategy_docs VALUES (42, 10, 'RELEASES')")
    conn.execute(
        "UPDATE harness_sessions SET current_item_id = 42 "
        "WHERE session_id = 'worker-1'"
    )

    facts = steering_visibility(
        conn,
        _rows() + [{"session_id": "holder-2", "project_id": 10, "project": "yoke"}],
        now=NOW,
    )
    group = facts["worker-1"]["steering_group_scope"]

    assert facts["worker-1"]["steering_group_session_id"] == "holder-2"
    assert group["holder_session_id"] == "holder-2"
    assert group["scope"]["document"] == "RELEASES"


def test_missing_covering_scope_is_not_normalized_wide() -> None:
    seat = {"claim_id": 1, "session_id": "h", "claimed_at": "t"}
    for scope in (None, {}, {"document": "CURRENT-PLAN"}):
        group = _covering_group_scope({**seat, "scope": scope}, {})
        assert "scope" not in group
        assert group["strategy_docs"] == []
