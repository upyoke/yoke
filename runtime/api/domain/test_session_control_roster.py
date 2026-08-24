"""Read-time fleet roster enrichment and capability projection tests."""

from __future__ import annotations

from datetime import datetime, timezone
import json
import sqlite3

import pytest

from runtime.api.test_constants import TEST_ITEM_ID, TEST_ITEM_REF
from yoke_core.domain.session_control_roster import (
    SESSION_CONTROL_ROSTER_FIELDS,
    session_control_roster_result,
)


NOW = datetime(2026, 8, 22, 12, 1, tzinfo=timezone.utc)


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
            turn_posture TEXT,
            turn_posture_at TEXT
        );
        CREATE TABLE session_relays (
            relay_id TEXT PRIMARY KEY,
            machine_id TEXT,
            connected_until TEXT,
            state TEXT,
            surface_versions TEXT,
            project_checkouts TEXT
        );
        CREATE TABLE work_claims (
            id INTEGER PRIMARY KEY,
            session_id TEXT,
            target_kind TEXT,
            item_id INTEGER,
            epic_id INTEGER,
            task_num INTEGER,
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
        """
    )
    return conn


def _add_session(
    conn: sqlite3.Connection,
    *,
    surface: str,
    version: str,
    posture: str = "running",
    project_id: int = 10,
) -> None:
    conn.execute(
        "INSERT INTO harness_sessions VALUES (?,?,?,?,?,?,?,?,?,?)",
        (
            "session-1",
            project_id,
            surface,
            version,
            "machine-1",
            "2026-08-22T12:00:00Z",
            "2026-08-22T12:00:00Z",
            None,
            posture,
            "2026-08-22T12:00:00Z",
        ),
    )


def _add_relay(
    conn: sqlite3.Connection,
    *,
    surface_versions: dict[str, str],
    project_ids: tuple[int, ...] = (10,),
) -> None:
    conn.execute(
        "INSERT INTO session_relays VALUES (?,?,?,?,?,?)",
        (
            "relay-1",
            "machine-1",
            "2026-08-22T12:05:00Z",
            "active",
            json.dumps(surface_versions),
            json.dumps(project_ids),
        ),
    )


def _base_row(*, surface: str, liveness: str) -> dict[str, object]:
    return {
        "session_id": "session-1",
        "project": "yoke",
        "claims": [],
        "executor": surface.split("-", 1)[0],
        "executor_surface": surface,
        "liveness": liveness,
    }


def test_roster_enriches_version_machine_relay_and_messageability() -> None:
    conn = _connection()
    _add_session(conn, surface="codex-desktop", version="26.814.41407")
    _add_relay(conn, surface_versions={"codex-desktop": "26.814.41407"})
    conn.execute(
        "INSERT INTO item_worktrees VALUES (?,?,?,?,?,?)",
        (1, TEST_ITEM_ID, "/repo/.worktrees/item-42", "item-42", "active", "worker"),
    )
    conn.execute(
        "INSERT INTO work_claims VALUES (?,?,?,?,?,?,?,?)",
        (
            1,
            "session-1",
            "item",
            TEST_ITEM_ID,
            None,
            None,
            "2026-08-22T11:00:00Z",
            None,
        ),
    )
    base = _base_row(surface="codex-desktop", liveness="active")
    base.update(
        {
            "claims": [{"target_kind": "item", "target": TEST_ITEM_REF}],
            "current_item": TEST_ITEM_REF,
            "work_role": "implementation",
            "workspace": "/repo",
            "messageability": {"messageable": False, "reason": "stale-cache"},
        }
    )

    result = session_control_roster_result([base], conn=conn, now=NOW)

    assert result["fields"] == list(SESSION_CONTROL_ROSTER_FIELDS)
    row = result["rows"][0]
    assert row["focus"] == TEST_ITEM_REF
    assert row["role"] == "implementation"
    assert row["worktree"] == "/repo/.worktrees/item-42"
    assert row["executor_version"] == "26.814.41407"
    assert row["machine_id"] == "machine-1"
    assert row["relay"] == "connected"
    assert row["turn_posture"] == "running"
    assert row["messageability"]["messageable"] is True
    assert row["messageability"]["relay_connected"] is True
    assert row["messageability"]["wake_available"] is True


def test_waiting_posture_uses_stopped_wake_capability() -> None:
    conn = _connection()
    _add_session(
        conn,
        surface="codex-cli",
        version="0.148.0-alpha.15",
        posture="waiting",
    )
    _add_relay(conn, surface_versions={"codex-cli": "0.148.0-alpha.15"})

    row = session_control_roster_result(
        [_base_row(surface="codex-cli", liveness="active")],
        conn=conn,
        now=NOW,
    )["rows"][0]

    assert row["turn_posture"] == "waiting"
    assert row["messageability"]["wake_operation"] == "message_stopped"
    assert row["messageability"]["wake_interface"] == "supported"
    assert row["messageability"]["wake_available"] is True


def test_stopped_desktop_session_wakes_through_the_machines_installed_cli() -> None:
    conn = _connection()
    _add_session(conn, surface="claude-desktop", version="1.34493.1")
    _add_relay(conn, surface_versions={"claude-cli": "2.1.241"})

    routing = session_control_roster_result(
        [_base_row(surface="claude-desktop", liveness="ended")],
        conn=conn,
        now=NOW,
    )["rows"][0]["messageability"]

    assert routing["wake_operation"] == "message_stopped"
    assert routing["wake_interface"] == "supported"
    assert routing["wake_available"] is True


def test_machine_wake_needs_a_relay_serving_the_sessions_project() -> None:
    conn = _connection()
    _add_session(conn, surface="claude-desktop", version="1.34493.1")
    _add_relay(conn, surface_versions={"claude-cli": "2.1.241"}, project_ids=(11,))

    routing = session_control_roster_result(
        [_base_row(surface="claude-desktop", liveness="ended")],
        conn=conn,
        now=NOW,
    )["rows"][0]["messageability"]

    assert routing["relay_connected"] is True
    assert routing["wake_interface"] == "none"
    assert routing["wake_available"] is False


def test_private_wake_route_requires_the_exact_pinned_version() -> None:
    conn = _connection()
    _add_session(conn, surface="claude-desktop", version="1.34493.1")
    _add_relay(conn, surface_versions={"claude-desktop": "1.32885.1"})

    routing = session_control_roster_result(
        [_base_row(surface="claude-desktop", liveness="stale")],
        conn=conn,
        now=NOW,
    )["rows"][0]["messageability"]

    assert routing["hook_injection"] is True
    assert routing["wake_operation"] == "message_idle"
    assert routing["wake_interface"] == "none"
    assert routing["wake_available"] is False


@pytest.mark.parametrize(
    ("surface_versions", "project_ids"),
    (
        ({"codex-cli": "0.148.0-alpha.15"}, (10,)),
        ({"codex-desktop": "26.813.1"}, (10,)),
        ({"codex-desktop": "26.814.41407"}, (11,)),
    ),
)
def test_connected_relay_is_not_wakeable_without_an_exact_route(
    surface_versions: dict[str, str],
    project_ids: tuple[int, ...],
) -> None:
    conn = _connection()
    _add_session(conn, surface="codex-desktop", version="26.814.41407")
    _add_relay(conn, surface_versions=surface_versions, project_ids=project_ids)

    routing = session_control_roster_result(
        [_base_row(surface="codex-desktop", liveness="active")],
        conn=conn,
        now=NOW,
    )["rows"][0]["messageability"]

    assert routing["relay_connected"] is True
    assert routing["wake_available"] is False


def test_empty_roster_has_the_complete_stable_field_contract() -> None:
    assert session_control_roster_result([]) == {
        "fields": list(SESSION_CONTROL_ROSTER_FIELDS),
        "rows": [],
    }
