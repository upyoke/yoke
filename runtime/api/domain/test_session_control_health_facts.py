"""Declared-wait and open-probe facts behind the roster's health state."""

from __future__ import annotations

from runtime.api.domain.session_control_health_facts_test_support import (
    BLOCKER as BLOCKER,
    DEPENDENT as DEPENDENT,
    SESSION as SESSION,
    WORKFLOW_VERSION as WORKFLOW_VERSION,
    conn as conn,
)


import sqlite3

import pytest

from yoke_core.domain.session_control_health_facts import session_health_facts
from yoke_core.domain.session_stale_alive_probe import probe_key
from yoke_core.domain.work_claim_targets import make_item_target


def _rows() -> list[dict[str, object]]:
    return [{"session_id": SESSION}]


def _add_edge(connection: sqlite3.Connection, *, gate_point: str) -> None:
    connection.execute(
        "INSERT INTO item_dependencies (id,dependent_item_id,blocking_item_id,gate_point,satisfaction) VALUES (?,?,?,?,?)",
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


def test_a_partial_schema_reports_absent_facts_rather_than_failing() -> None:
    """A schema missing a joined table yields no fact, never a read error.

    The roster is a read-only projection, so a universe or fixture carrying
    only some of the tables these reads span must still answer.
    """
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    connection.executescript(
        """
        CREATE TABLE work_claims (
            id INTEGER PRIMARY KEY,
            session_id TEXT,
            target_kind TEXT,
            scope TEXT,
            claimed_at TEXT,
            released_at TEXT
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

    assert session_health_facts(connection, _rows(), {})[SESSION] == {
        "declared_wait": None,
        "stale_alive_probe": None,
    }


@pytest.mark.parametrize("gate,satisfaction,held,status,expected", [
    ("integration", "fact:merged", True, "implementing", True),
    ("activation", "status:done", True, "implementing", True),
    ("integration", "status:done", True, "done", False),
    ("coordination_only", "status:done", True, "implementing", False),
    ("integration", "fact:deployed:prod", True, "implementing", False),
    ("integration", "status:done", False, "implementing", False),
])
def test_claim_dependency_fact_uses_only_woken_edges(
    test_db, gate, satisfaction, held, status, expected
):
    from runtime.api.fixtures.backlog_inserts import insert_item
    from yoke_core.domain.project_identity import render_item_ref
    from yoke_core.domain.session_control_health_facts import gating_blockers
    from yoke_core.domain.sessions_holdings_claim_facts import claimed_item_facts

    dependent, blocker, other = 9811, 9812, 9813
    for item in (dependent, blocker, other):
        insert_item(test_db, id=item, project_sequence=item, workflow_id="dash",
                    status=status if item == blocker else "implementing")
    test_db.execute(
        "INSERT INTO item_dependencies "
        "(dependent_item_id,blocking_item_id,gate_point,satisfaction,source,created_at) "
        "VALUES (%s,%s,%s,%s,'test','2026-01-01T00:00:00Z')",
        (dependent if held else other, blocker, gate, satisfaction),
    )
    facts = claimed_item_facts(test_db, [dependent, blocker])
    assert facts[dependent]["item_awaiting_dependency"] == (
        f"{render_item_ref(test_db, blocker)} {gate}" if expected else ""
    )
    assert facts[blocker]["item_awaiting_dependency"] == ""
    if satisfaction.startswith("fact:deployed:"):
        assert dependent in gating_blockers(test_db, [dependent])
        assert gating_blockers(test_db, [dependent], woken_edges_only=True) == {}
