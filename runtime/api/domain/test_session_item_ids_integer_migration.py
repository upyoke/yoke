"""0118 retypes the session item-id columns from TEXT to INTEGER.

A database still carrying the TEXT declaration keeps its numeric ids,
loses only the non-numeric legacy values (``''`` and the May 2026
sentinels), and ends with both columns ``integer``. A database already on
INTEGER (fresh installs, replay) is left untouched.
"""

from pathlib import Path

import pytest

from runtime.api.fixtures.session_holdings import insert_session
from yoke_core.domain import migrations
from yoke_core.domain.migration_history import load_migration_module

_COLUMNS = ("current_item_id", "recent_item_id")


def _migration():
    path = Path(migrations.__file__).parent / "0118_session_item_ids_integer.py"
    return load_migration_module(path, path.stem)


def _types(conn):
    rows = conn.execute(
        "SELECT column_name, data_type FROM information_schema.columns "
        "WHERE table_schema = current_schema() AND table_name = 'harness_sessions' "
        "AND column_name IN ('current_item_id', 'recent_item_id')"
    ).fetchall()
    return {str(row[0]): str(row[1]) for row in rows}


def _seed(conn, session_id, current, recent):
    insert_session(conn, session_id)
    conn.execute(
        "UPDATE harness_sessions SET current_item_id = %s, recent_item_id = %s "
        "WHERE session_id = %s",
        (current, recent, session_id),
    )


def _values(conn):
    rows = conn.execute(
        "SELECT session_id, current_item_id, recent_item_id FROM harness_sessions "
        "WHERE session_id LIKE 'mig-%' ORDER BY session_id"
    ).fetchall()
    return [(row[0], row[1], row[2]) for row in rows]


def _make_text(conn):
    for column in _COLUMNS:
        conn.execute(f"ALTER TABLE harness_sessions ALTER COLUMN {column} TYPE TEXT")


def test_fresh_schema_declares_both_columns_integer(test_db):
    assert _types(test_db) == {"current_item_id": "integer", "recent_item_id": "integer"}
    _migration().invariants(test_db)


def test_text_columns_keep_numeric_ids_and_null_legacy_values(test_db):
    _make_text(test_db)
    _seed(test_db, "mig-1", "41", "007")
    _seed(test_db, "mig-2", "", "DOCTOR")
    _seed(test_db, "mig-3", None, "STRATEGIZE")
    _seed(test_db, "mig-4", "12", "")
    test_db.commit()
    with pytest.raises(AssertionError, match="0118_session_item_ids_integer"):
        _migration().invariants(test_db)

    _migration().apply(test_db)
    test_db.commit()

    assert _types(test_db) == {"current_item_id": "integer", "recent_item_id": "integer"}
    assert _values(test_db) == [
        ("mig-1", 41, 7),
        ("mig-2", None, None),
        ("mig-3", None, None),
        ("mig-4", 12, None),
    ]
    _migration().invariants(test_db)


def test_replay_on_integer_columns_is_a_no_op(test_db):
    _seed(test_db, "mig-1", 41, 7)
    test_db.commit()

    _migration().apply(test_db)
    _migration().apply(test_db)
    test_db.commit()

    assert _types(test_db) == {"current_item_id": "integer", "recent_item_id": "integer"}
    assert _values(test_db) == [("mig-1", 41, 7)]
    _migration().invariants(test_db)
