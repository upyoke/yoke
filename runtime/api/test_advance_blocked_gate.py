"""advance preflight refuses items.blocked=1."""

from __future__ import annotations

import pytest

from runtime.api.fixtures import pg_testdb
from runtime.api.fixtures.schema_ddl import apply_fixture_ddl
from yoke_core.domain.advance_blocked_gate import evaluate


@pytest.fixture
def conn():
    name = pg_testdb.create_test_database()
    c = pg_testdb.connect_test_database(name)
    # The refusal names the item inside an unblock recipe, so the fixture
    # carries the identity that reference is read from.
    apply_fixture_ddl(
        c,
        """
        CREATE TABLE projects (
            id INTEGER PRIMARY KEY,
            slug TEXT,
            public_item_prefix TEXT
        );
        CREATE TABLE items (
            id INTEGER PRIMARY KEY,
            project_id INTEGER,
            project_sequence INTEGER,
            blocked INTEGER DEFAULT 0,
            blocked_reason TEXT
        );
        """,
    )
    c.execute(
        "INSERT INTO projects (id, slug, public_item_prefix) "
        "VALUES (1, 'yoke', 'YOK')"
    )
    yield c
    c.close()
    pg_testdb.drop_test_database(name)


def _add(conn, item_id, blocked=0, reason=None):
    conn.execute(
        "INSERT INTO items "
        "(id, project_id, project_sequence, blocked, blocked_reason) "
        "VALUES (%s, 1, %s, %s, %s)",
        (item_id, item_id, blocked, reason),
    )


def test_clear_when_unblocked(conn):
    _add(conn, 1, blocked=0)
    decision = evaluate(conn, 1)
    assert decision.blocked is False


def test_blocked_with_reason(conn):
    _add(conn, 2, blocked=1, reason="Awaiting external API contract")
    decision = evaluate(conn, 2)
    assert decision.blocked is True
    assert decision.reason == "Awaiting external API contract"
    assert decision.rendered_blocker is not None
    assert "yoke items unblock YOK-2" in decision.rendered_blocker
    assert "Awaiting external API contract" in decision.rendered_blocker


def test_blocked_without_reason(conn):
    _add(conn, 3, blocked=1, reason=None)
    decision = evaluate(conn, 3)
    assert decision.blocked is True
    assert decision.reason is None
    assert decision.rendered_blocker is not None


def test_missing_item(conn):
    decision = evaluate(conn, 999)
    assert decision.blocked is False
    assert decision.rendered_blocker is None
