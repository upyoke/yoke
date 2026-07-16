"""Shared helpers for the migration_apply pytest suites.

Split out of the original ``test_migration_apply.py`` so each authored test
file stays under the 350-line limit. Lives outside the ``test_*.py``
collection pattern so pytest does not pick it up as a test module. Each split
file imports the ``apply_env`` fixture from this module so the heavy
DB/worktree setup is authored exactly once.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Optional

import pytest

from runtime.api.conftest import insert_item
from yoke_core.domain import db_backend
from runtime.api.fixtures.migration_model_test import governed_postgres_test_seed
from yoke_core.domain.migration_apply_targets import (
    POSTGRES_VALIDATION_ENV_SUFFIX,
)
from yoke_core.domain.project_seed_test_helpers import SEED_PROJECT_IDS
from yoke_core.domain.schema_init_apply import execute_schema_script
from runtime.api.test_backlog import _conn, tmp_db  # noqa: F401 — reused fixture
from runtime.api.fixtures.machine_config_test import register_machine_checkout


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
    status TEXT,
    failure_reason TEXT,
    started_at TEXT,
    completed_at TEXT,
    duration_ms INTEGER,
    state TEXT,
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
    actor_id TEXT,
    worktree TEXT,
    source_branch TEXT,
    source_commit TEXT,
    integration_target TEXT,
    change_class TEXT
);

CREATE TABLE IF NOT EXISTS coordination_leases (
    id INTEGER PRIMARY KEY,
    project_id INTEGER NOT NULL,
    lease_key TEXT NOT NULL,
    session_id TEXT NOT NULL,
    actor_id TEXT,
    acquired_at TEXT NOT NULL,
    heartbeat_at TEXT,
    released_at TEXT,
    release_reason TEXT
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_coordination_leases_live
    ON coordination_leases(project_id, lease_key) WHERE released_at IS NULL;
"""


def _placeholder(conn) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


_TEST_MIGRATION_BODY = '''"""Test migration module for two-unit apply tests.

The module creates a ``widgets`` table and optionally fails via invariants
when the ``RAISE_INVARIANT`` marker row is present — tests use that hook
to exercise the FAIL_TEST_VERIFY branch.
"""

from yoke_core.domain.schema_common import _table_exists

def apply(conn):
    conn.execute(
        "CREATE TABLE IF NOT EXISTS widgets ("
        "  id INTEGER PRIMARY KEY,"
        "  name TEXT NOT NULL"
        ")"
    )

def invariants(conn):
    assert _table_exists(conn, "widgets"), "widgets table missing after apply"
    # Tests that want to trigger an invariant failure create a
    # `trip_invariants` table ahead of time; its existence forces a raise.
    if _table_exists(conn, "trip_invariants"):
        raise AssertionError("invariant tripwire table present")
'''


_RAISING_MIGRATION_BODY = '''"""Migration that raises on apply — exercises FAIL_TEST_APPLY."""

def apply(conn):
    raise RuntimeError("synthetic module.apply() failure")
'''


_NO_APPLY_MIGRATION_BODY = '''"""Migration missing the apply() surface."""

# intentionally no apply()
'''


# Invariants-tripping migration: apply() always succeeds; invariants() raises
# when the YOKE_TRIP_LIVE_VERIFY env marker is set. Tests exercise the
# FAIL_LIVE_VERIFY branch by flipping the marker between rehearse and
# live-apply.
_LIVE_VERIFY_TRIP_BODY = '''"""Migration that passes apply() but fails invariants on demand."""

import os

def apply(conn):
    conn.execute(
        "CREATE TABLE IF NOT EXISTS widgets ("
        "  id INTEGER PRIMARY KEY,"
        "  name TEXT NOT NULL"
        ")"
    )

def invariants(conn):
    if os.environ.get("YOKE_TRIP_LIVE_VERIFY") == "1":
        raise AssertionError("synthetic live-verify failure")
'''


@pytest.fixture
def apply_env(tmp_db: str, tmp_path: Path, monkeypatch):
    """Prepare a control DB + local checkout + modules_dir + authoritative DB.

    Returns a dict with the paths individual tests need plus a helper
    for writing additional migration modules at runtime.
    """
    worktree = tmp_path / "yoke-repo"
    worktree.mkdir(parents=True, exist_ok=True)
    modules_dir = worktree / "runtime" / "api" / "domain" / "migrations"
    modules_dir.mkdir(parents=True, exist_ok=True)
    (modules_dir / "__init__.py").write_text("", encoding="utf-8")
    (modules_dir / "sample_migration.py").write_text(
        _TEST_MIGRATION_BODY, encoding="utf-8"
    )

    # Pre-create the project-local backup dir so backup guards see the
    # active shape exercised by governed migration apply.
    (worktree / ".yoke" / "backups").mkdir(parents=True, exist_ok=True)
    authoritative_db = db_backend.resolve_pg_dsn()

    # Control DB setup.
    conn = _conn(tmp_db)
    try:
        execute_schema_script(conn, _EXTRA_DDL)
        p = _placeholder(conn)
        register_machine_checkout(
            tmp_path / "machine-config", worktree, SEED_PROJECT_IDS["yoke"]
        )
        conn.execute(
            "INSERT INTO projects "
            "(id, slug, name, public_item_prefix, created_at) "
            f"VALUES ({p}, {p}, {p}, {p}, {p}) "
            "ON CONFLICT (id) DO UPDATE SET "
            "slug = excluded.slug, name = excluded.name, "
            "public_item_prefix = excluded.public_item_prefix, "
            "created_at = excluded.created_at",
            (
                SEED_PROJECT_IDS["yoke"], "yoke", "Yoke",
                "YOK", "2026-04-23T00:00:00Z",
            ),
        )
        seed = governed_postgres_test_seed()
        seed["models"]["primary"]["runner"]["config"]["modules_dir"] = (
            "runtime/api/domain/migrations"
        )
        seed_json = json.dumps(seed, sort_keys=True)
        conn.execute(
            "INSERT INTO project_capabilities "
            "(project_id, type, settings, created_at) "
            f"VALUES ({p}, {p}, {p}, {p})",
            (SEED_PROJECT_IDS["yoke"], "migration_model", seed_json,
             "2026-04-23T00:00:00Z"),
        )
        conn.commit()
    finally:
        conn.close()

    (worktree / ".yoke").mkdir(parents=True, exist_ok=True)
    validation_db = worktree / ".yoke" / "validation.db"
    from runtime.api.fixtures import pg_testdb

    validation_db_name = pg_testdb.create_test_database()
    validation_dsn = pg_testdb.dsn_for_test_database(validation_db_name)
    _seed_postgres_validation_db(validation_dsn)
    monkeypatch.setenv(
        f"YOKE_PG_DSN{POSTGRES_VALIDATION_ENV_SUFFIX}",
        validation_dsn,
    )

    monkeypatch.setenv("YOKE_DB", tmp_db)

    try:
        yield {
            "control_db": tmp_db,
            "worktree": worktree,
            "modules_dir": modules_dir,
            "authoritative_db": str(authoritative_db),
            "validation_db": str(validation_db),
            "validation_dsn": validation_dsn,
        }
    finally:
        pg_testdb.drop_test_database(validation_db_name)


def _seed_postgres_validation_db(validation_dsn: str) -> None:
    conn = db_backend.connect_psycopg(validation_dsn)
    try:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS items ("
            " id INTEGER PRIMARY KEY,"
            " title TEXT,"
            " created_at TEXT"
            ")"
        )
        conn.commit()
    finally:
        conn.close()


def _connect_validation_db(apply_env):
    return db_backend.connect_psycopg(apply_env["validation_dsn"])


def _seed_apply_item(
    control_db: str,
    *,
    item_id: int,
    modules=("sample_migration",),
    intent: str = "apply",
    compatibility_class: str = "pre_merge_safe",
    count_preserving: bool = True,
    rehearsal_commands=(),
) -> None:
    profile: Dict[str, Any] = {
        "state": "declared",
        "model_name": "primary",
        "mutation_intent": intent,
        "migration_modules": list(modules),
        "compatibility_class": compatibility_class,
        "schema_kinds": ["additive"],
        "data_kinds": [],
        "affected_surfaces": [{"table": "widgets"}],
        "count_preserving": count_preserving,
    }
    if intent == "apply":
        profile["migration_strategy"] = "additive_only"
    attestation: Dict[str, Any] = {
        "pre_merge_readers_writers": [
            {"path": "runtime/api/widgets.py", "role": "writer"}
        ],
        "invariants": ["widgets table exists after apply"],
        "rehearsal_commands": list(rehearsal_commands),
        "residual_risk_notes": "additive table; no pre-merge readers",
    }
    conn = _conn(control_db)
    try:
        insert_item(
            conn,
            id=item_id,
            project="yoke",
            status="implementing",
            db_mutation_profile=json.dumps(profile, sort_keys=True),
            db_compatibility_attestation=json.dumps(attestation, sort_keys=True),
        )
        conn.commit()
    finally:
        conn.close()


def _audit_row(authoritative_db: str, audit_id: int) -> Optional[Dict[str, Any]]:
    # Postgres models write audit rows to the model's authoritative DB through
    # raw psycopg. Read back through the same native connection family rather
    # than the generic backend compatibility seam.
    conn = db_backend.connect_psycopg(authoritative_db)
    try:
        cur = conn.execute(
            "SELECT * FROM migration_audit WHERE id = %s", (audit_id,),
        )
        row = cur.fetchone()
        columns = []
        for desc in cur.description or []:
            name = getattr(desc, "name", None)
            columns.append(name if name is not None else desc[0])
    finally:
        conn.close()
    return dict(zip(columns, row)) if row else None
