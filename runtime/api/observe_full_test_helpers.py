"""Shared sample payloads and DB-fixture builders for ``test_observe_full*``.

Filename omits the ``test_`` prefix so pytest does not collect it. Each split
file imports the SAMPLE_* constants and the ``make_*`` builders, then wraps
the builders in a local ``@pytest.fixture`` shim. This keeps fixtures local
to their consumer files (so future moves do not pull surprise dependencies)
while sharing the verbose schema DDL and sample payloads.
"""

from __future__ import annotations

import contextlib
from dataclasses import dataclass
from pathlib import Path

from runtime.api.fixtures import pg_testdb
from runtime.api.fixtures.file_test_db import init_test_db
from runtime.api.fixtures.schema_ddl import apply_fixture_ddl


SAMPLE_BASH_SUCCESS = {
    "tool_name": "Bash",
    "tool_input": {"command": "echo hello"},
    "tool_response": {"content": "hello\n"},
    "tool_use_id": "tu-abc123",
}

SAMPLE_BASH_FAILURE = {
    "tool_name": "Bash",
    "tool_input": {"command": "false"},
    "tool_response": {"content": "Exit code 1"},
    "error": "Exit code 1",
    "tool_use_id": "tu-bash-fail",
}

SAMPLE_EDIT_FAILURE = {
    "tool_name": "Edit",
    "tool_input": {"file_path": "/tmp/foo.py", "old_string": "a", "new_string": "b"},
    "tool_response": {},
    "error": "String to replace not found in file",
    "tool_use_id": "tu-edit-fail",
}

SAMPLE_WRITE_EVENT = {
    "tool_name": "Write",
    "tool_input": {"file_path": "/tmp/output.txt"},
    "tool_response": {"content": "File written"},
}

SAMPLE_READ_EVENT = {
    "tool_name": "Read",
    "tool_input": {"file_path": "/tmp/input.py"},
    "tool_response": {"content": "file contents"},
}

SAMPLE_GREP_FAILURE = {
    "tool_name": "Grep",
    "tool_input": {"pattern": "foo"},
    "tool_response": {},
    "error": "No matches found for pattern",
    "tool_use_id": "tu-grep-fail",
}


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
        "INSERT INTO projects "
        "(id, slug, name, github_repo, public_item_prefix, created_at) "
        "VALUES (1, 'yoke', 'Yoke', 'org/yoke', 'YOK', "
        "'2026-01-01T00:00:00Z')"
    )


_EVENTS_DDL = """CREATE TABLE events (
    id INTEGER PRIMARY KEY,
    event_id TEXT UNIQUE NOT NULL,
    source_type TEXT NOT NULL,
    session_id TEXT NOT NULL,
    severity TEXT NOT NULL DEFAULT 'INFO',
    event_kind TEXT NOT NULL,
    event_type TEXT NOT NULL,
    event_name TEXT NOT NULL,
    event_outcome TEXT,
    service TEXT NOT NULL DEFAULT 'cli',
    project_id INTEGER NOT NULL DEFAULT 1,
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
    created_at TEXT NOT NULL
)"""


def make_events_db_conn():
    """Row-shape events double for parser/analysis tests.

    Mints a disposable Postgres test database (dropped when the connection
    closes) carrying only the minimal projects + events tables; file-backed
    observe fixtures in this module go through ``init_test_db``.
    """
    name = pg_testdb.create_test_database()
    conn = pg_testdb.connect_test_database(name)
    pg_testdb.drop_database_on_close(conn, name)
    apply_fixture_ddl(conn, _PROJECTS_DDL)
    _seed_projects(conn)
    apply_fixture_ddl(conn, _EVENTS_DDL)
    conn.commit()
    return conn


def _apply_events_schema() -> None:
    """Build the minimal events schema on the active test backend."""
    from yoke_core.domain import db_backend

    conn = db_backend.connect()
    try:
        apply_fixture_ddl(conn, _PROJECTS_DDL)
        _seed_projects(conn)
        apply_fixture_ddl(conn, _EVENTS_DDL)
    finally:
        conn.close()


@contextlib.contextmanager
def make_events_db_file(tmp_path):
    """Yield a backend-aware DB-path token with the events table."""
    with init_test_db(Path(tmp_path), apply_schema=_apply_events_schema) as db_path:
        yield db_path


def _apply_attribution_schema() -> None:
    """Build the minimal attribution schema on the active test backend."""
    from yoke_core.domain import db_backend

    conn = db_backend.connect()
    try:
        apply_fixture_ddl(
            conn,
            _PROJECTS_DDL
            + """
            CREATE TABLE items (
                id INTEGER PRIMARY KEY,
                project_id INTEGER DEFAULT 1,
                type TEXT NOT NULL DEFAULT 'task',
                status TEXT NOT NULL DEFAULT 'planned',
                worktree TEXT
            );
            CREATE TABLE epic_dispatch_chains (
                epic_id TEXT NOT NULL,
                worktree_path TEXT NOT NULL,
                current_task TEXT
            );
            """
            + _EVENTS_DDL,
        )
        _seed_projects(conn)
    finally:
        conn.close()


@dataclass(frozen=True)
class AttributionDbFile:
    """Backend-aware attribution DB token plus filesystem project root."""

    db_path: str
    repo_root: Path


@contextlib.contextmanager
def make_attribution_db_file(tmp_path):
    """Yield a DB token and repo root for attribution resolution tests."""
    repo_root = Path(tmp_path) / "repo"
    repo_root.mkdir()
    with init_test_db(Path(tmp_path), apply_schema=_apply_attribution_schema) as db_path:
        yield AttributionDbFile(db_path=db_path, repo_root=repo_root)


__all__ = [
    "SAMPLE_BASH_SUCCESS",
    "SAMPLE_BASH_FAILURE",
    "SAMPLE_EDIT_FAILURE",
    "SAMPLE_WRITE_EVENT",
    "SAMPLE_READ_EVENT",
    "SAMPLE_GREP_FAILURE",
    "AttributionDbFile",
    "make_events_db_conn",
    "make_events_db_file",
    "make_attribution_db_file",
    "Path",
]
