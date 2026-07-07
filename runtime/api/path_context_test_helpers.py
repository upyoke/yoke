"""Shared test helpers for path-context and continuity coverage."""

from __future__ import annotations

import os
import uuid
from typing import Any, Optional

from yoke_core.domain import db_backend
from yoke_core.domain import project_structure as ps
from yoke_core.domain.db_helpers import iso8601_now
from yoke_core.domain.schema_init_tables import create_path_registry_tables


NOW = "2026-04-30T12:00:00Z"


_EVENTS_DDL = """
    CREATE TABLE events (
        event_id TEXT UNIQUE NOT NULL,
        source_type TEXT NOT NULL,
        session_id TEXT NOT NULL,
        severity TEXT NOT NULL DEFAULT 'INFO',
        event_kind TEXT NOT NULL,
        event_type TEXT NOT NULL,
        event_name TEXT NOT NULL,
        service TEXT NOT NULL DEFAULT 'cli',
        project_id INTEGER DEFAULT 1,
        envelope TEXT,
        created_at TEXT NOT NULL
    )
"""

_PROJECTS_DDL = """
    CREATE TABLE projects (
        id INTEGER PRIMARY KEY,
        slug TEXT NOT NULL UNIQUE,
        name TEXT,
        public_item_prefix TEXT NOT NULL DEFAULT 'YOK',
        created_at TEXT
    );
    INSERT INTO projects (id, slug, name, public_item_prefix, created_at)
    VALUES (1, 'yoke', 'Yoke', 'YOK', '2026-01-01T00:00:00Z')
"""


def _p(conn) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def _build_minimal_schema(conn) -> None:
    """Create the minimal events + projects + path-registry + project_structure
    schema on a single connection so the tables co-locate on one backend.

    ``ps.cmd_init`` opens its own connection, so it cannot be used for a
    co-located build; route through the connection-passing DDL owner
    ``create_project_structure_tables`` instead.
    """
    conn.execute(_EVENTS_DDL)
    conn.execute(_PROJECTS_DDL)
    create_path_registry_tables(conn)
    ps.create_project_structure_tables(conn)
    conn.commit()


def init_minimal_schema(db_path: str):
    """Build the minimal continuity/path-context schema on the active backend.

    Creates a disposable per-call Postgres test database with
    ``YOKE_PG_DSN`` repointed at it. The returned facade connection's
    ``close()`` restores the prior DSN and drops the database, so the existing
    ``c = init_minimal_schema(...); ...; c.close()`` call shape works
    unchanged.
    """
    del db_path

    from runtime.api.fixtures import pg_testdb

    name = pg_testdb.create_test_database()
    new_dsn = pg_testdb.dsn_for_test_database(name)
    prior = os.environ.get(db_backend.PG_DSN_ENV)
    os.environ[db_backend.PG_DSN_ENV] = new_dsn
    conn = db_backend.connect()
    _build_minimal_schema(conn)

    _base_close = conn.close

    def _close_and_drop():
        _base_close()
        if prior is not None:
            os.environ[db_backend.PG_DSN_ENV] = prior
        else:
            os.environ.pop(db_backend.PG_DSN_ENV, None)
        pg_testdb.drop_test_database(name)

    conn.close = _close_and_drop
    return conn


def emit_event(conn: Any, *, name: str = "TestEvent") -> str:
    event_id = str(uuid.uuid4())
    p = _p(conn)
    conn.execute(
        "INSERT INTO events (event_id, source_type, session_id, severity, "
        "event_kind, event_type, event_name, service, project_id, created_at, "
        f"envelope) VALUES ({p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, 1, "
        f"{p}, {p})",
        (
            event_id,
            "system",
            "test",
            "INFO",
            "telemetry",
            "system",
            name,
            "cli",
            iso8601_now(),
            "{}",
        ),
    )
    conn.commit()
    return event_id


def mint_target(
    conn: Any,
    project: str,
    path_string: str,
    kind: str = "file",
    parent_target_id: Optional[int] = None,
) -> int:
    p = _p(conn)
    project_id = 1 if project == "yoke" else int(project)
    cur = conn.execute(
        "INSERT INTO path_targets "
        "(project_id, kind, path_string, generation, parent_target_id, created_at) "
        f"VALUES ({p}, {p}, {p}, 1, {p}, {p}) RETURNING id",
        (project_id, kind, path_string, parent_target_id, iso8601_now()),
    )
    return int(cur.fetchone()[0])
