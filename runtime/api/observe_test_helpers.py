"""Shared sample payloads and DB-fixture builders for ``test_observe_*``.

Filename omits the ``test_`` prefix so pytest does not collect it. Each split
file imports the SAMPLE_* constants and the ``make_*`` builders, then wraps
the builders in a local ``@pytest.fixture`` shim. This keeps fixtures local
to their consumer files (so future moves do not pull surprise dependencies)
while sharing the verbose schema DDL and sample payloads.

Distinct from ``observe_full_test_helpers`` because these consumers use a
thinner schema (no ``id`` PK, no NOT NULL constraints) suited to minimal
drive-by tests.
"""

from __future__ import annotations

from runtime.api.fixtures import pg_testdb
from runtime.api.fixtures.schema_ddl import apply_fixture_ddl


SAMPLE_POST_TOOL_USE = {
    "tool_name": "Bash",
    "tool_input": {"command": "echo hello"},
    "tool_response": {
        "content": "hello\n",
    },
    "tool_use_id": "tu-abc123",
}

SAMPLE_POST_TOOL_USE_FAILURE = {
    "tool_name": "Edit",
    "tool_input": {"file_path": "/tmp/foo.py", "old_string": "a", "new_string": "b"},
    "tool_response": {},
    "error": "String to replace not found in file",
    "tool_use_id": "tu-fail456",
}

SAMPLE_BASH_FAILURE = {
    "tool_name": "Bash",
    "tool_input": {"command": "false"},
    "tool_response": {"content": "Exit code 1"},
    "error": "Exit code 1",
    "tool_use_id": "tu-bash-fail",
}


_EVENTS_DDL = """CREATE TABLE events (
    event_id TEXT PRIMARY KEY,
    source_type TEXT,
    session_id TEXT,
    severity TEXT,
    event_kind TEXT,
    event_type TEXT,
    event_name TEXT,
    event_outcome TEXT,
    service TEXT,
    project_id INTEGER,
    item_id TEXT,
    task_num INTEGER,
    agent TEXT,
    tool_name TEXT,
    duration_ms INTEGER,
    exit_code INTEGER,
    anomaly_flags TEXT,
    tool_use_id TEXT,
    turn_id TEXT,
    hook_event_name TEXT,
    envelope TEXT,
    created_at TEXT
)"""


_PROJECTS_DDL = """CREATE TABLE projects (
    id INTEGER PRIMARY KEY,
    slug TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    github_repo TEXT,
    public_item_prefix TEXT NOT NULL DEFAULT 'YOK',
    created_at TEXT NOT NULL DEFAULT ''
);"""


def _seed_projects(conn) -> None:
    conn.execute(
        _PROJECTS_SEED_DDL
    )


_PROJECTS_SEED_DDL = (
    "INSERT INTO projects "
    "(id, slug, name, github_repo, public_item_prefix, created_at) "
    "VALUES (1, 'yoke', 'Yoke', 'org/yoke', 'YOK', "
    "'2026-01-01T00:00:00Z');"
)


def make_memory_db():
    """Create a row-shape double with the minimal events table.

    Mints a disposable Postgres test database (dropped when the connection
    closes); these tests exercise event-envelope row normalization only, so
    the schema stays minimal rather than cloning the full fixture schema.
    """
    name = pg_testdb.create_test_database()
    conn = pg_testdb.connect_test_database(name)
    pg_testdb.drop_database_on_close(conn, name)
    apply_fixture_ddl(conn, _PROJECTS_DDL)
    _seed_projects(conn)
    apply_fixture_ddl(conn, _EVENTS_DDL)
    conn.commit()
    return conn


__all__ = [
    "SAMPLE_POST_TOOL_USE",
    "SAMPLE_POST_TOOL_USE_FAILURE",
    "SAMPLE_BASH_FAILURE",
    "make_memory_db",
]
