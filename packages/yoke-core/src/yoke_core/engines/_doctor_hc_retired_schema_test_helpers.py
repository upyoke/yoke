"""Shared scaffolding for HC-retired-schema-resurrection tests.

Splits the control-plane connection builders and registry writer out of
the test modules so each authored test file stays under the 350-line
limit. The two control-conn builders model the two ``authoritative_db``
kinds the HC resolves:

* :func:`_make_control_conn` — a Postgres control-plane double declaring an
  external ``sqlite_file`` target. The HC probes the on-disk SQLite file the
  capability declares (the legacy non-Yoke project-DB branch); the tests
  stage that file themselves.
* :func:`_make_pg_control_conn` — a context manager yielding a Postgres
  test connection where the connected control plane is the schema target.
"""

from __future__ import annotations

from contextlib import contextmanager
import json
from pathlib import Path
from typing import Iterator

from runtime.api.fixtures.schema_ddl import apply_fixture_ddl
from runtime.api.fixtures.machine_config_test import register_machine_checkout


def _project_id(project: str) -> int:
    return {"yoke": 1, "buzz": 2}.get(project, 99)


def _make_control_conn(tmp_path: Path, auth_db: Path, *, project: str = "buzz"):
    """Control-plane DB declaring an external ``sqlite_file`` model.

    Mints a disposable Postgres database dropped when the connection
    closes. The declared authoritative target stays an on-disk SQLite
    file — that file is the HC's probe subject, not this connection.
    """
    from runtime.api.fixtures import pg_testdb

    name = pg_testdb.create_test_database()
    conn = pg_testdb.connect_test_database(name)
    apply_fixture_ddl(
        conn,
        """
        CREATE TABLE projects (
            id INTEGER PRIMARY KEY,
            slug TEXT UNIQUE,
            name TEXT,
            public_item_prefix TEXT DEFAULT 'YOK',
            created_at TEXT
        );
        CREATE TABLE project_capabilities (
            id INTEGER PRIMARY KEY,
            project_id INTEGER,
            type TEXT,
            config TEXT,
            settings TEXT,
            created_at TEXT
        );
        """
    )
    # Write the model so authoritative_db.location.path resolves under this
    # machine's mapped checkout for the project.
    register_machine_checkout(tmp_path.parent, tmp_path, _project_id(project))
    rel_path = auth_db.relative_to(tmp_path)
    conn.execute(
        "INSERT INTO projects "
        "(id, slug, name, public_item_prefix, created_at) "
        "VALUES (%s, %s, %s, %s, %s)",
        (
            _project_id(project),
            project,
            project.capitalize(),
            "YOK",
            "2026-04-24T00:00:00Z",
        ),
    )
    settings = json.dumps(
        {
            "models": {
                "primary": {
                    "authoritative_db": {
                        "kind": "sqlite_file",
                        "location": {"path": str(rel_path)},
                    }
                }
            }
        },
        sort_keys=True,
    )
    conn.execute(
        "INSERT INTO project_capabilities "
        "(project_id, type, config, settings, created_at) "
        "VALUES (%s, %s, %s, %s, %s)",
        (_project_id(project), "migration_model", settings, settings,
         "2026-04-24T00:00:00Z"),
    )
    conn.commit()
    return pg_testdb.drop_database_on_close(conn, name)


@contextmanager
def _make_pg_control_conn(tmp_path: Path) -> Iterator[object]:
    """Yield a control-plane conn declaring a Postgres schema target.

    For ``kind == 'postgres'`` the connected control plane is the schema
    target, so the HC probes this same connection's catalog through
    the backend-aware ``schema_common`` helpers. Retired surfaces are
    simulated by creating them on this Postgres-backed test connection.
    """

    def apply_schema() -> None:
        from yoke_core.domain import db_backend

        conn = db_backend.connect()
        try:
            apply_fixture_ddl(
                conn,
                """
                CREATE TABLE projects (
                    id INTEGER PRIMARY KEY,
                    slug TEXT UNIQUE,
                    name TEXT,
                    public_item_prefix TEXT DEFAULT 'YOK',
                    created_at TEXT
                );
                CREATE TABLE project_capabilities (
                    id INTEGER PRIMARY KEY,
                    project_id INTEGER,
                    type TEXT,
                    config TEXT,
                    settings TEXT,
                    created_at TEXT
                );
                """,
            )
            conn.execute(
                "INSERT INTO projects "
                "(id, slug, name, public_item_prefix, created_at) "
                "VALUES (%s, %s, %s, %s, %s)",
                (
                    _project_id("yoke"),
                    "yoke",
                    "Yoke",
                    "YOK",
                    "2026-04-24T00:00:00Z",
                ),
            )
            settings = json.dumps(
                {
                    "models": {
                        "primary": {
                            "authoritative_db": {
                                "kind": "postgres",
                                "location": {"database_name": "yoke_prod"},
                            }
                        }
                    }
                },
                sort_keys=True,
            )
            conn.execute(
                "INSERT INTO project_capabilities "
                "(project_id, type, config, settings, created_at) "
                "VALUES (%s, %s, %s, %s, %s)",
                (
                    _project_id("yoke"),
                    "migration_model",
                    settings,
                    settings,
                    "2026-04-24T00:00:00Z",
                ),
            )
            conn.commit()
        finally:
            conn.close()

    from runtime.api.fixtures.file_test_db import connect_test_db, init_test_db

    with init_test_db(tmp_path, apply_schema=apply_schema) as db_path:
        conn = connect_test_db(db_path)
        try:
            yield conn
        finally:
            conn.close()


def _write_registry(root: Path, body: str) -> None:
    target = root / "runtime" / "api" / "domain" / "retired_schema_surfaces.yaml"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(body, encoding="utf-8")
