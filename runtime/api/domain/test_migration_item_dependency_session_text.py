"""Ordered migration coverage for text dependency-edge session ids.

The fixture is a converged universe with ``item_dependencies.session_id``
put back to the INTEGER column the entry converts, holding one stored value
and one NULL.
"""

from __future__ import annotations

import importlib

import pytest

from runtime.api.conftest import insert_item
from yoke_core.domain.schema_api_context_tables_core import CORE_TABLES

ENTRY_NAME = "0081_item_dependency_session_text"


def _entry():
    return importlib.import_module(f"yoke_core.domain.migrations.{ENTRY_NAME}")


def _column_type(conn) -> str:
    return conn.execute(
        "SELECT data_type FROM information_schema.columns "
        "WHERE table_name = 'item_dependencies' AND column_name = 'session_id'"
    ).fetchone()[0]


def _edge(conn, dependent: int, blocking: int, session_id) -> None:
    conn.execute(
        "INSERT INTO item_dependencies (dependent_item_id, blocking_item_id, "
        "source, session_id, created_at) VALUES (%s, %s, 'operator', %s, now())",
        (dependent, blocking, session_id),
    )


def test_entry_declares_no_serving_floor() -> None:
    assert not hasattr(_entry(), "MINIMUM_SERVING_VERSION")


def test_apply_converts_an_integer_column_keeping_values_and_nulls(test_db) -> None:
    for item_id in (1, 2, 3):
        insert_item(test_db, id=item_id, title=f"item {item_id}")
    test_db.execute(
        "ALTER TABLE item_dependencies ALTER COLUMN session_id TYPE INTEGER USING NULL"
    )
    _edge(test_db, 1, 2, 42)
    _edge(test_db, 1, 3, None)
    assert _column_type(test_db) == "integer"

    _entry().apply(test_db)
    _entry().apply(test_db)
    _entry().invariants(test_db)

    assert _column_type(test_db) == "text"
    stored = test_db.execute(
        "SELECT blocking_item_id, session_id FROM item_dependencies "
        "ORDER BY blocking_item_id"
    ).fetchall()
    assert [tuple(row) for row in stored] == [(2, "42"), (3, None)]


def test_invariants_refuse_an_integer_column(test_db) -> None:
    test_db.execute(
        "ALTER TABLE item_dependencies ALTER COLUMN session_id TYPE INTEGER USING NULL"
    )
    with pytest.raises(AssertionError, match="session_id is integer"):
        _entry().invariants(test_db)


def test_schema_packet_seed_matches_the_converged_table(test_db) -> None:
    live = test_db.execute(
        "SELECT column_name, data_type FROM information_schema.columns "
        "WHERE table_name = 'item_dependencies' ORDER BY ordinal_position"
    ).fetchall()
    seeded = CORE_TABLES["item_dependencies"]["columns"]
    live_types = {name: kind for name, kind in live}
    assert [name for name, _ in seeded] == [name for name, _ in live]
    assert live_types["session_id"] == "text"
    assert dict(seeded)["session_id"] == "TEXT"
