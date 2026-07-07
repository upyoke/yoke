"""Shared helpers for the db_mutation_gate pytest suites.

Split out of the original ``test_db_mutation_gate.py`` so each authored test
file stays under the 350-line limit. Lives outside the ``test_*.py``
collection pattern so pytest does not pick it up as a test module. Each split
file declares its own small ``gate_db`` fixture and imports the heavier
seeding helpers below.
"""

from __future__ import annotations

import contextlib
import json
import sqlite3
from pathlib import Path
from typing import Any, Iterator, Mapping, Tuple

from yoke_core.domain.db_mutation_gate import decision_record_path
from yoke_core.domain import db_backend
from yoke_core.domain.project_identity import resolve_project_id
from yoke_core.domain.project_seed_test_helpers import SEED_PROJECT_IDS
from runtime.api.fixtures.file_test_db import (
    apply_fixture_schema_ddl,
    connect_test_db,
    init_test_db,
)
from runtime.api.fixtures.machine_config_test import register_machine_checkout
from yoke_core.domain.schema_init_apply import execute_schema_script


def _upsert_set(*columns: str) -> str:
    return ", ".join(f"{column} = excluded.{column}" for column in columns)


def _placeholder(conn: sqlite3.Connection) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


_PROJECT_UPSERT_SET = _upsert_set("name", "created_at")
_FLOW_UPSERT_SET = _upsert_set("project_id", "name", "stages", "created_at")


_EXTRA_DDL = """
CREATE TABLE IF NOT EXISTS project_capabilities (
    id INTEGER PRIMARY KEY,
    project_id INTEGER NOT NULL,
    type TEXT NOT NULL,
    
    settings TEXT DEFAULT '{}',
    verified_at TEXT,
    created_at TEXT NOT NULL,
    UNIQUE(project_id, type)
);

CREATE TABLE IF NOT EXISTS migration_audit (
    id INTEGER PRIMARY KEY,
    migration_name TEXT NOT NULL,
    description TEXT,
    tables_declared TEXT,
    expected_deltas TEXT,
    pre_row_counts TEXT,
    post_row_counts TEXT,
    pre_fk_violations INTEGER,
    post_fk_violations INTEGER,
    backup_path TEXT,
    state TEXT,
    failure_reason TEXT,
    exception_reason TEXT,
    source_fingerprint TEXT,
    rehearsed_at TEXT,
    lease_id INTEGER,
    test_copy_path TEXT,
    baseline_verify_result TEXT,
    author_verify_result TEXT,
    session_id TEXT,
    model_name TEXT,
    project_id INTEGER,
    started_at TEXT,
    completed_at TEXT,
    duration_ms INTEGER
);
"""


def _apply_gate_schema() -> None:
    """``init_test_db`` apply_schema strategy: fixture ``SCHEMA_DDL`` + relaxed
    ``migration_audit``.

    ``SCHEMA_DDL`` builds items / projects / project_capabilities /
    deployment_flows but omits ``migration_audit`` (a governed table that
    ``cmd_init`` creates separately). The gate reads ``migration_audit`` through
    ``db_helpers.connect(audit_path)``; on Postgres that resolves to the
    per-test DSN database, so the table must live there too. ``_EXTRA_DDL``'s
    relaxed (nullable, no-``CHECK``) shape is used deliberately so the tests'
    minimal column-subset audit inserts succeed — the canonical
    ``ensure_migration_audit_table`` DDL marks ``tables_declared`` /
    ``expected_deltas`` / ``pre_row_counts`` / ``backup_path`` ``NOT NULL``.
    The ``project_capabilities`` re-declaration inside ``_EXTRA_DDL`` is a
    no-op (``IF NOT EXISTS``) since ``SCHEMA_DDL`` already created it.
    """
    from yoke_core.domain import db_backend

    apply_fixture_schema_ddl()
    conn = db_backend.connect()
    try:
        execute_schema_script(conn, _EXTRA_DDL)
        conn.commit()
    finally:
        conn.close()


@contextlib.contextmanager
def gate_db_context(tmp_path: Path) -> Iterator[Tuple[sqlite3.Connection, Path]]:
    """Backend-aware ``gate_db`` fixture body shared by the gate suites.

    Routes the gate's items+audit database through :func:`init_test_db` so the
    same per-test database carries the seeded items / projects / capabilities /
    flows *and* the ``migration_audit`` rows the gate reads via
    ``db_helpers.connect(audit_path)``. On SQLite that is a real file under
    ``tmp_path``; on Postgres a disposable per-test DSN database. Tests use
    :func:`gate_audit_path` for the ``audit_db_path`` argument so the gate's own
    connection lands on the same database on both backends.
    """
    with init_test_db(tmp_path, apply_schema=_apply_gate_schema) as db_path:
        conn = connect_test_db(db_path)
        try:
            yield conn, tmp_path
        finally:
            conn.close()


def gate_audit_path(tmp_path: Path) -> str:
    """The audit-DB path token matching :func:`init_test_db`'s db_path.

    On SQLite this is the same file the fixture's ``conn`` opened, so the gate's
    ``db_helpers.connect(audit_path)`` reads the seeded ``migration_audit``. On
    Postgres the path is ignored (the connection target is the repointed DSN),
    but the per-test database already carries the table.
    """
    return str(tmp_path / "yoke.db")


def ensure_audit_table(audit_path: str) -> None:
    """Idempotently create the relaxed ``migration_audit`` on ``audit_path``.

    Needed for the project-configured-model test whose authoritative DB is a
    fresh path (``app/data/app.db``) the fixture strategy never touched. On
    SQLite this creates the table in that file; on Postgres the ``IF NOT
    EXISTS`` DDL is a harmless no-op against the per-test DSN database that
    already carries the table.
    """
    conn = connect_test_db(audit_path)
    try:
        execute_schema_script(conn, _EXTRA_DDL)
        conn.commit()
    finally:
        conn.close()


def seed_audit_row(
    tmp_path: Path,
    *,
    columns: str,
    placeholders: str,
    values: tuple,
    audit_path: str | None = None,
) -> None:
    """Insert one ``migration_audit`` row through the backend-aware connection.

    Replaces the raw ``sqlite3.connect(audit_path)`` seeding the gate suites
    used: on Postgres that wrote a SQLite file the gate never read. Routes
    through :func:`connect_test_db` so the row lands in the per-test database
    the gate resolves. ``audit_path`` defaults to :func:`gate_audit_path`; pass
    an explicit path for the project-configured-model test whose gate resolves a
    different authoritative-DB path.
    """
    path = audit_path or gate_audit_path(tmp_path)
    conn = connect_test_db(path)
    try:
        marker = "%s" if db_backend.connection_is_postgres(conn) else "?"
        native_placeholders = placeholders.replace("?", marker)
        conn.execute(
            f"INSERT INTO migration_audit ({columns}) VALUES ({native_placeholders})",
            values,
        )
        conn.commit()
    finally:
        conn.close()


def create_table_on_audit_db(tmp_path: Path, ddl: str) -> None:
    """Run a ``CREATE TABLE`` against the gate's audit database (post-state tests).

    Backend-aware counterpart to the raw ``sqlite3.connect(audit_path)`` the
    post-state drift tests used to materialize a surface table.
    """
    conn = connect_test_db(gate_audit_path(tmp_path))
    try:
        conn.execute(ddl)
        conn.commit()
    finally:
        conn.close()


def _seed_capability(conn: sqlite3.Connection, project: str, settings: Mapping[str, Any]) -> None:
    raw = json.dumps(settings, sort_keys=True)
    p = _placeholder(conn)
    project_id = resolve_project_id(conn, project)
    conn.execute(
        "INSERT INTO project_capabilities "
        f"(project_id, type, settings, created_at) VALUES ({p}, {p}, {p}, {p}) "
        "ON CONFLICT (project_id, type) DO UPDATE SET "
        "settings = excluded.settings, created_at = excluded.created_at",
        (project_id, "migration_model", raw, "2026-04-23T00:00:00Z"),
    )
    conn.commit()


def _seed_project(
    conn: sqlite3.Connection, project: str, repo_path: Path
) -> None:
    p = _placeholder(conn)
    project_id = SEED_PROJECT_IDS.get(project)
    if project_id is None:
        row = conn.execute(
            f"SELECT COALESCE(MAX(id), 0) + 1 FROM projects"
        ).fetchone()
        project_id = int(row[0])
    register_machine_checkout(repo_path.parent, repo_path, project_id)
    conn.execute(
        "INSERT INTO projects "
        "(id, slug, name, public_item_prefix, created_at) "
        f"VALUES ({p}, {p}, {p}, {p}, {p}) "
        f"ON CONFLICT (id) DO UPDATE SET {_PROJECT_UPSERT_SET}",
        (project_id, project, project, "YOK", "2026-04-23T00:00:00Z"),
    )
    conn.commit()


def _seed_flow_with_migration_apply(
    conn: sqlite3.Connection,
    project: str,
    flow_id: str = "test-flow",
    model_name: str = "primary",
    lifecycle_phase: str = "implementing",
) -> None:
    p = _placeholder(conn)
    stages = json.dumps([
        {"kind": "migration_apply", "model_name": model_name,
         "lifecycle_phase": lifecycle_phase},
        {"name": "merged", "executor": "auto"},
    ])
    conn.execute(
        "INSERT INTO deployment_flows "
        f"(id, project_id, name, stages, created_at) VALUES ({p}, {p}, {p}, {p}, {p}) "
        f"ON CONFLICT (id) DO UPDATE SET {_FLOW_UPSERT_SET}",
        (flow_id, resolve_project_id(conn, project), flow_id, stages, "2026-04-23T00:00:00Z"),
    )
    conn.commit()


def _write_module(repo_path: Path, modules_dir: str, identifier: str, body: str = '') -> Path:
    target = repo_path / modules_dir / f"{identifier}.py"
    target.parent.mkdir(parents=True, exist_ok=True)
    if not body:
        body = (
            "MIGRATION = '''\n"
            "ALTER TABLE items ADD COLUMN demo TEXT DEFAULT NULL;\n"
            "'''\n"
        )
    target.write_text(body, encoding="utf-8")
    return target


def _write_decision_record(
    repo_path: Path,
    identifier: str,
    *,
    model_name: str = "primary",
    retired: bool = True,
    reason: str = "Module never applied; supersedes inline backfill.",
) -> Path:
    target = decision_record_path(repo_path, identifier)
    target.parent.mkdir(parents=True, exist_ok=True)
    body = (
        "---\n"
        f"retired-without-apply: {'true' if retired else 'false'}\n"
        f"migration_module: {identifier}\n"
        f"model_name: {model_name}\n"
        "retired_at: 2026-04-23T00:00:00Z\n"
        f"reason: {reason}\n"
        "---\n\n"
        "Justification body.\n"
    )
    target.write_text(body, encoding="utf-8")
    return target
