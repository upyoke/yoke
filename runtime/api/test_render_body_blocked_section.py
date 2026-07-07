"""rendered body adds a ``## Block`` section when blocked=1.

The section is absent when blocked=0, names the operator-supplied reason
verbatim, and degrades gracefully when blocked_reason is null. Updated_at
is included when present.
"""

from __future__ import annotations

import pytest

from runtime.api.fixtures import pg_testdb
from runtime.api.fixtures.schema_ddl import apply_fixture_ddl
from yoke_core.domain.render_body_blocked import render_blocked_section


def _items_conn(ddl: str):
    name = pg_testdb.create_test_database()
    c = pg_testdb.connect_test_database(name)
    apply_fixture_ddl(c, ddl)
    return pg_testdb.drop_database_on_close(c, name)


@pytest.fixture
def conn():
    c = _items_conn(
        """
        CREATE TABLE items (
            id INTEGER PRIMARY KEY,
            title TEXT,
            blocked INTEGER DEFAULT 0,
            blocked_reason TEXT,
            updated_at TEXT
        );
        """
    )
    yield c
    c.close()


def _add(conn, item_id, blocked=0, blocked_reason=None, updated_at=None):
    conn.execute(
        "INSERT INTO items (id, title, blocked, blocked_reason, updated_at) "
        "VALUES (%s, %s, %s, %s, %s)",
        (item_id, f"Item {item_id}", blocked, blocked_reason, updated_at),
    )


def test_returns_none_when_not_blocked(conn):
    _add(conn, 1, blocked=0)
    assert render_blocked_section(conn, 1) is None


def test_renders_section_with_reason_and_updated_at(conn):
    _add(
        conn, 2, blocked=1,
        blocked_reason="Awaiting external API contract",
        updated_at="2026-05-08T12:00:00Z",
    )
    out = render_blocked_section(conn, 2)
    assert out is not None
    assert out.startswith("## Block")
    assert "Awaiting external API contract" in out
    assert "2026-05-08T12:00:00Z" in out
    assert "/yoke unblock YOK-2" in out


def test_renders_with_missing_reason(conn):
    _add(conn, 3, blocked=1, blocked_reason=None)
    out = render_blocked_section(conn, 3)
    assert out is not None
    assert "(none recorded)" in out


def test_renders_with_missing_updated_at(conn):
    _add(conn, 4, blocked=1, blocked_reason="paused", updated_at=None)
    out = render_blocked_section(conn, 4)
    assert out is not None
    assert "Last updated" not in out
    assert "paused" in out


def test_returns_none_when_no_blocked_column():
    """The render is defensive: a partial schema without `blocked` skips."""
    c = _items_conn("CREATE TABLE items (id INTEGER PRIMARY KEY, title TEXT)")
    c.execute("INSERT INTO items (id, title) VALUES (1, 'x')")
    assert render_blocked_section(c, 1) is None
    c.close()


def test_returns_none_when_item_missing(conn):
    assert render_blocked_section(conn, 999) is None
