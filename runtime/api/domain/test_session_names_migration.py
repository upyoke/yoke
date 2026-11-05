"""Assignment migration preserves history and is safe to repeat."""

import importlib
import sqlite3

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
