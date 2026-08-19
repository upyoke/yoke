"""The minimal database reflection-capture writes into.

Capture persists learning-log rows and nothing else, so its tests carry
just `projects` and `ouroboros_entries` rather than the full fixture
schema. One definition, because a column added to the real table has to
reach every capture test at once or they fail as a group.
"""

from __future__ import annotations

from runtime.api.engines._doctor_native_sql_test_helpers import (
    connect_disposable_test_db,
)
from yoke_core.domain.schema_init_apply import execute_schema_script

REFLECTION_DB_DDL = """\
    CREATE TABLE projects (
        id INTEGER PRIMARY KEY,
        slug TEXT UNIQUE,
        name TEXT,
        public_item_prefix TEXT DEFAULT 'YOK'
    );
    INSERT INTO projects (id, slug, name, public_item_prefix)
    VALUES (1, 'yoke', 'Yoke', 'YOK');
    CREATE TABLE ouroboros_entries (
        id INTEGER PRIMARY KEY,
        timestamp TEXT NOT NULL,
        agent TEXT NOT NULL,
        context TEXT,
        category TEXT NOT NULL,
        body TEXT NOT NULL,
        reviewed_at TEXT,
        archived_at TEXT,
        project_id INTEGER,
        target_project_id INTEGER,
        created_at TEXT NOT NULL DEFAULT ''
    );
"""


def make_reflection_db():
    """Create a disposable test DB with the tables capture writes."""
    conn = connect_disposable_test_db()
    execute_schema_script(conn, REFLECTION_DB_DDL)
    conn.commit()
    return conn


__all__ = ["REFLECTION_DB_DDL", "make_reflection_db"]
