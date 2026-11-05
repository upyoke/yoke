"""Assignment migration preserves history and is safe to repeat."""

import importlib
import sqlite3

import pytest

from yoke_core.domain.item_refs_schema import ensure_item_refs_view


def test_launch_assignment_backfill_and_drop():
    conn = sqlite3.connect(":memory:")
    conn.executescript("""
        CREATE TABLE projects(id INTEGER PRIMARY KEY,public_item_prefix TEXT);
        INSERT INTO projects VALUES (1,'APP'),(2,'OTHER');
        CREATE TABLE items(id INTEGER PRIMARY KEY,project_id INTEGER,project_sequence INTEGER);
        INSERT INTO items VALUES (73,1,12),(74,2,12);
        CREATE TABLE session_launches(launch_id TEXT PRIMARY KEY,project_id INTEGER,session_name TEXT);
        INSERT INTO session_launches VALUES
            ('assigned',1,'APP-12: Old title'),
            ('unassigned',1,NULL),('wrong-project',2,'APP-12: Work'),
            ('unstructured',1,'Scratch chat'),('gone',1,'APP-99: Deleted');
    """)
    ensure_item_refs_view(conn)
    migration = importlib.import_module(
        "yoke_core.domain.migrations.0103_session_names"
    )
    migration.apply(conn)
    migration.invariants(conn)
    migration.apply(conn)
    assert dict(conn.execute("SELECT launch_id,item_id FROM session_launches")) == {
        "assigned": 73,
        "unassigned": None,
        "wrong-project": None,
        "unstructured": None,
        "gone": None,
    }
    assert "session_name" not in {
        row[1] for row in conn.execute("PRAGMA table_info(session_launches)")
    }


def test_assignment_invariant_retains_the_model_level_work_purpose():
    conn = sqlite3.connect(":memory:")
    conn.executescript("""
        CREATE TABLE universe_settings(key TEXT PRIMARY KEY,value TEXT);
        CREATE TABLE items(id INTEGER PRIMARY KEY,project_id INTEGER);
        INSERT INTO items VALUES (73,1);
        CREATE TABLE session_launches(launch_id TEXT,project_id INTEGER,
            item_id INTEGER,requested_level TEXT,level_placement TEXT);
        INSERT INTO session_launches VALUES ('assigned',1,73,NULL,'{}');
    """)
    migration = importlib.import_module(
        "yoke_core.domain.migrations.0103_session_names"
    )
    assert "0071_model_effort_levels" in migration.RETIRES_INVARIANTS
    with pytest.raises(AssertionError, match="unconverged work purpose"):
        migration.invariants(conn)
    conn.execute(
        "UPDATE session_launches SET level_placement=?",
        ('{"work_required":true}',),
    )
    migration.invariants(conn)
    # No override follows the shipped setting; malformed overrides still refuse.
    conn.execute(
        "INSERT INTO universe_settings VALUES ('cursor_quota_order',?)",
        ('["Cursor Models","Cursor Models"]',),
    )
    from yoke_core.domain.quota_pool_order import QuotaPoolOrderError

    with pytest.raises(QuotaPoolOrderError) as raised:
        migration.invariants(conn)
    assert raised.value.code == "cursor_quota_order_invalid"
    conn.execute(
        "UPDATE universe_settings SET value=?",
        ('["Other Models","Cursor Models"]',),
    )
    migration.invariants(conn)
