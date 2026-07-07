"""Shared fixtures and helpers for the regression tests.

The retire and apply variants of the regression both need:

* The ``regression_db`` fixture (extends ``tmp_db`` with the governed-
  mutation tables, a Yoke seed, and the Postgres migration-audit surface the
  model resolves).
* ``_seed_governed_item`` — stages an item with a governed mutation
  profile plus a satisfied verification-phase QA requirement so the
  mutations-layer QA gate doesn't fire and the DB-mutation gate is the
  only remaining gate that can block.
* ``_advance_status`` — drives the canonical mutator with the bypasses
  the regression tests need.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict
from unittest import mock

import pytest

from runtime.api.conftest import insert_item
from runtime.api.fixtures.machine_config_test import register_machine_checkout
from yoke_core.domain import backlog_updates
from yoke_core.domain.migration_model_capability import yoke_primary_seed
from runtime.api.fixtures.schema_ddl import apply_fixture_ddl
from runtime.api.test_backlog import (
    _conn,
    _patch_externals,
    tmp_db,  # noqa: F401 — re-exported fixture
)


# ---------------------------------------------------------------------------
# Fixture extensions — load the governed-mutation surface into tmp_db
# ---------------------------------------------------------------------------


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


@pytest.fixture
def regression_db(tmp_db: str, tmp_path: Path):
    """``tmp_db`` plus the governed-mutation tables and a Yoke seed.

    Returns a dict with ``db_path``, ``checkout_path``, and ``project`` so
    individual tests can stage items + evidence without per-test
    boilerplate.
    """
    repo_path = tmp_path / "yoke-repo"
    repo_path.mkdir(parents=True, exist_ok=True)

    conn = _conn(tmp_db)
    try:
        apply_fixture_ddl(conn, _EXTRA_DDL)
        register_machine_checkout(tmp_path / "machine-config", repo_path, 1)
        conn.execute(
            "INSERT INTO projects "
            "(id, slug, name, public_item_prefix, created_at) "
            "VALUES (%s, %s, %s, %s, %s) "
            "ON CONFLICT(id) DO UPDATE SET "
            "slug=excluded.slug, name=excluded.name, "
            "public_item_prefix=excluded.public_item_prefix",
            (1, "yoke", "Yoke", "YOK",
             "2026-04-23T00:00:00Z"),
        )
        seed_json = json.dumps(yoke_primary_seed(), sort_keys=True)
        conn.execute(
            "INSERT INTO project_capabilities "
            "(project_id, type, settings, created_at) "
            "VALUES (%s, %s, %s, %s)",
            (1, "migration_model", seed_json,
             "2026-04-23T00:00:00Z"),
        )
        # Seed Yoke's flow with the migration_apply stage so the joint
        # gate's flow cross-reference resolves cleanly when callers move
        # tickets through earlier transitions.  Even though this test only
        # drives implementing -> reviewing-implementation, having the flow
        # stage in place keeps the migration_model bootstrap honest.
        stages_json = json.dumps([
            {"kind": "migration_apply", "model_name": "primary",
             "lifecycle_phase": "implementing"},
            {"name": "merged", "executor": "auto"},
        ])
        conn.execute(
            "INSERT INTO deployment_flows "
            "(id, project_id, name, description, stages, on_failure, "
            " target_env, created_at) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
            ("yoke-internal", 1, "Internal", "Test flow",
             stages_json, "halt", None, "2026-04-23T00:00:00Z"),
        )
        conn.commit()
    finally:
        conn.close()

    return {
        "db_path": tmp_db,
        "checkout_path": repo_path,
        "project": "yoke",
    }


def _seed_governed_item(
    db_path: str,
    *,
    item_id: int,
    profile: Dict[str, Any],
    status: str = "implementing",
) -> None:
    conn = _conn(db_path)
    try:
        insert_item(
            conn,
            id=item_id,
            project="yoke",
            status=status,
            db_mutation_profile=json.dumps(profile, sort_keys=True),
        )
        # Seed a satisfied verification-phase QA requirement so the
        # mutations-layer QA gate passes and the DB-mutation gate is
        # the only remaining gate that can fire.  This isolates the
        # the regression to the new evidence path.
        cur = conn.execute(
            "INSERT INTO qa_requirements "
            "(item_id, qa_kind, qa_phase, blocking_mode, "
            " requirement_source, success_policy, created_at) "
            "VALUES (%s, 'ac_verification', 'verification', 'blocking', "
            "        'seeded_default', 'satisfied-by-test', %s) "
            "RETURNING id",
            (item_id, "2026-04-23T00:00:00Z"),
        )
        req_id = cur.fetchone()[0]
        conn.execute(
            "INSERT INTO qa_runs "
            "(qa_requirement_id, executor_type, qa_kind, verdict, "
            " created_at) "
            "VALUES (%s, 'pytest', 'ac_verification', 'pass', %s)",
            (req_id, "2026-04-23T00:00:00Z"),
        )
        conn.commit()
    finally:
        conn.close()


def _advance_status(db_path: str, item_id: int, target: str) -> dict:
    """Drive the canonical mutator with all the bypasses tests need."""
    env_patches = {
        "YOKE_DB": db_path,
        "YOKE_CLAIM_BYPASS": "regression-test",
    }
    with mock.patch.dict(os.environ, env_patches, clear=False):
        with _patch_externals():
            return backlog_updates.execute_update(
                item_id=item_id,
                field="status",
                value=target,
                rebuild_board=False,
            )
