"""Declared-wait and open-probe facts behind the roster's health state."""

from __future__ import annotations

import sqlite3

import pytest

from yoke_core.domain import json_helper
from yoke_core.domain.builtin_workflow_definitions import (
    builtin_workflow_definition,
)
from yoke_core.domain.session_control_health_facts import session_health_facts
from yoke_core.domain.session_stale_alive_probe import probe_key
from yoke_core.domain.work_claim_targets import make_item_target
from yoke_core.domain.workflow_definition_codec import definition_digest


SESSION = "session-1"
DEPENDENT = 41
BLOCKER = 42
WORKFLOW_VERSION = 7


@pytest.fixture()
def conn() -> sqlite3.Connection:
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    connection.executescript(
        """
        CREATE TABLE projects (id INTEGER PRIMARY KEY, slug TEXT, prefix TEXT);
        CREATE TABLE items (
            id INTEGER PRIMARY KEY,
            project_id INTEGER,
            project_sequence INTEGER,
            status TEXT,
            merged_at TEXT,
            workflow_id TEXT,
            workflow_version_id INTEGER
        );
        CREATE TABLE item_dependencies (
            id INTEGER PRIMARY KEY,
            dependent_item_id INTEGER,
            blocking_item_id INTEGER,
            gate_point TEXT,
            satisfaction TEXT
        );
        CREATE TABLE workflow_versions (
            id INTEGER PRIMARY KEY,
            version INTEGER,
            definition_json TEXT,
            definition_digest TEXT
        );
        CREATE TABLE item_worktrees (
            id INTEGER PRIMARY KEY,
            item_id INTEGER,
            branch TEXT,
            state TEXT,
            lane_role TEXT
        );
        CREATE TABLE work_claims (
            id INTEGER PRIMARY KEY,
            session_id TEXT,
            target_kind TEXT,
            scope TEXT,
            claimed_at TEXT,
            released_at TEXT
        );
        CREATE TABLE session_messages (
            message_id TEXT PRIMARY KEY,
            idempotency_key TEXT,
            cancelled_at TEXT,
            expires_at TEXT
        );
        CREATE TABLE session_message_recipients (
            message_id TEXT,
            session_id TEXT,
            state TEXT,
            created_at TEXT,
            wake_attempt_count INTEGER
        );
        """
    )
    connection.execute("INSERT INTO projects VALUES (1,'yoke','YOK')")
    fixture = builtin_workflow_definition("dash")
    definition = fixture["definition"]
    connection.execute(
        "INSERT INTO workflow_versions VALUES (?,?,?,?)",
        (
            WORKFLOW_VERSION,
            int(fixture["canon_version"]),
            json_helper.dumps(definition),
            definition_digest(definition),
        ),
    )
    for item_id, status in ((DEPENDENT, "implementing"), (BLOCKER, "implementing")):
        connection.execute(
            "INSERT INTO items VALUES (?,?,?,?,?,?,?)",
            (item_id, 1, item_id, status, None, "dash", WORKFLOW_VERSION),
        )
    connection.execute(
        "INSERT INTO work_claims VALUES (?,?,?,?,?,?)",
        (
            1,
            SESSION,
            "item",
            make_item_target(DEPENDENT).scope_json(),
            "2026-08-22T11:00:00Z",
            None,
        ),
    )
    return connection


def _rows() -> list[dict[str, object]]:
    return [{"session_id": SESSION}]


def _add_edge(connection: sqlite3.Connection, *, gate_point: str) -> None:
    connection.execute(
        "INSERT INTO item_dependencies VALUES (?,?,?,?,?)",
        (1, DEPENDENT, BLOCKER, gate_point, "status:done"),
    )


def _add_probe(connection: sqlite3.Connection, *, state: str) -> None:
    connection.execute(
        "INSERT INTO session_messages VALUES (?,?,?,?)",
        ("message-1", probe_key(SESSION), None, "2099-01-01T00:00:00Z"),
    )
    connection.execute(
        "INSERT INTO session_message_recipients VALUES (?,?,?,?,?)",
        ("message-1", SESSION, state, "2026-08-22T11:50:00Z", 1),
    )


def test_no_declaration_and_no_probe_leaves_the_quiet_unaccounted(conn) -> None:
    facts = session_health_facts(conn, _rows(), {})[SESSION]

    assert facts["declared_wait"] is None
    assert facts["stale_alive_probe"] is None


def test_a_gating_edge_on_a_claimed_item_is_a_declared_wait(conn) -> None:
    _add_edge(conn, gate_point="activation")

    facts = session_health_facts(conn, _rows(), {})[SESSION]

    assert facts["declared_wait"] == {
        "kind": "dependency",
        "item": "YOK-41",
        "blocking_item": "YOK-42",
        "gate_point": "activation",
        "blocking_status": "implementing",
    }


def test_a_satisfied_blocker_no_longer_declares_a_wait(conn) -> None:
    _add_edge(conn, gate_point="activation")
    conn.execute("UPDATE items SET status=? WHERE id=?", ("done", BLOCKER))

    assert session_health_facts(conn, _rows(), {})[SESSION]["declared_wait"] is None


def test_an_unpinned_blocker_stays_a_wait_because_nothing_can_verify_it(conn) -> None:
    _add_edge(conn, gate_point="activation")
    conn.execute(
        "UPDATE items SET status=?,workflow_version_id=NULL WHERE id=?",
        ("done", BLOCKER),
    )

    facts = session_health_facts(conn, _rows(), {})[SESSION]

    assert facts["declared_wait"]["blocking_item"] == "YOK-42"


def test_a_coordination_only_edge_gates_nothing_so_declares_nothing(conn) -> None:
    _add_edge(conn, gate_point="coordination_only")

    assert session_health_facts(conn, _rows(), {})[SESSION]["declared_wait"] is None


def test_a_waiting_turn_posture_declares_the_wait_on_its_own(conn) -> None:
    identities = {SESSION: {"turn_posture": "waiting"}}

    facts = session_health_facts(conn, _rows(), identities)[SESSION]

    assert facts["declared_wait"] == {"kind": "turn_posture"}


def test_a_gating_edge_outranks_the_posture_because_it_names_the_blocker(conn) -> None:
    _add_edge(conn, gate_point="activation")
    identities = {SESSION: {"turn_posture": "waiting"}}

    facts = session_health_facts(conn, _rows(), identities)[SESSION]

    assert facts["declared_wait"]["kind"] == "dependency"


def test_an_outstanding_probe_is_reported_and_an_answered_one_is_not(conn) -> None:
    _add_probe(conn, state="injected")

    facts = session_health_facts(conn, _rows(), {})[SESSION]
    assert facts["stale_alive_probe"] == {
        "state": "injected",
        "created_at": "2026-08-22T11:50:00Z",
        "wake_attempt_count": 1,
    }

    conn.execute("UPDATE session_message_recipients SET state='acknowledged'")
    assert session_health_facts(conn, _rows(), {})[SESSION]["stale_alive_probe"] is None


def test_an_ordinary_message_is_not_a_probe(conn) -> None:
    conn.execute(
        "INSERT INTO session_messages VALUES (?,?,?,?)",
        ("message-9", "operator-note", None, "2099-01-01T00:00:00Z"),
    )
    conn.execute(
        "INSERT INTO session_message_recipients VALUES (?,?,?,?,?)",
        ("message-9", SESSION, "injected", "2026-08-22T11:50:00Z", 0),
    )

    assert session_health_facts(conn, _rows(), {})[SESSION]["stale_alive_probe"] is None
