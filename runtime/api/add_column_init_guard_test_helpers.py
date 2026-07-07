"""Shared fixtures and helpers for the retired-schema regression suite.

Imported by ``test_add_column_init_guard.py``.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict
from unittest import mock

import pytest

from runtime.api.conftest import insert_item
from runtime.api.fixtures.machine_config_test import register_machine_checkout
from yoke_core.domain import (
    backlog_updates,
    db_backend,
    retired_schema_registry as rsr,
)
from yoke_core.domain.db_mutation_gate_implementing import (
    CONNECTED_POSTGRES_AUDIT_TOKEN,
)
from yoke_core.domain.migration_audit_schema import ensure_migration_audit_table
from yoke_core.domain.migration_model_capability import yoke_primary_seed
from runtime.api.test_backlog import (
    _conn,
    _patch_externals,
    tmp_db,  # noqa: F401  -- re-exported for fixture discovery
)


@pytest.fixture(autouse=True)
def _clear_registry_cache() -> None:
    rsr.clear_cache()
    yield
    rsr.clear_cache()


def _write_registry(root: Path, body: str) -> None:
    target = root / "runtime" / "api" / "domain" / "retired_schema_surfaces.yaml"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(body, encoding="utf-8")


def _placeholder(conn) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


@pytest.fixture
def regression_db(tmp_db: str, tmp_path: Path):
    """tmp_db + Yoke seed + connected Postgres audit evidence."""
    repo_path = tmp_path / "yoke-repo"
    repo_path.mkdir(parents=True, exist_ok=True)
    conn = _conn(tmp_db)
    try:
        p = _placeholder(conn)
        ensure_migration_audit_table(conn)
        register_machine_checkout(tmp_path / "machine-config", repo_path, 1)
        conn.execute(
            "INSERT INTO projects (id, slug, name, created_at) "
            f"VALUES ({p}, {p}, {p}, {p})",
            (1, "yoke", "Yoke", "2026-04-24T00:00:00Z"),
        )
        seed_json = json.dumps(yoke_primary_seed(), sort_keys=True)
        conn.execute(
            "INSERT INTO project_capabilities "
            "(project, type, settings, created_at) "
            f"VALUES ({p}, {p}, {p}, {p})",
            ("yoke", "migration_model", seed_json,
             "2026-04-24T00:00:00Z"),
        )
        stages_json = json.dumps([
            {"kind": "migration_apply", "model_name": "primary",
             "lifecycle_phase": "implementing"},
            {"name": "merged", "executor": "auto"},
        ])
        conn.execute(
            "INSERT INTO deployment_flows "
            "(id, project, name, description, stages, on_failure, "
            f" target_env, created_at) VALUES ({p}, {p}, {p}, {p}, "
            f"{p}, {p}, {p}, {p})",
            ("yoke-internal", "yoke", "Internal", "Test flow",
             stages_json, "halt", None, "2026-04-24T00:00:00Z"),
        )
        # The destructive-post-state check reads the authoritative DB. Under
        # the Postgres model that is the connected authority, so seed the drift
        # there rather than materializing a repo-local ``data/yoke.db`` file.
        conn.execute("ALTER TABLE projects ADD COLUMN legacy_retired_col TEXT")
        conn.execute(
            "INSERT INTO migration_audit "
            "(migration_name, state, project_id, model_name, tables_declared, "
            "expected_deltas, pre_row_counts, backup_path, started_at) "
            f"VALUES ({p}, 'completed', 'yoke', 'primary', "
            f"'[]', '{{}}', '{{}}', '', {p})",
            ("legacy_cutover", "2026-04-24T00:00:00Z"),
        )
        conn.commit()
    finally:
        conn.close()

    # Synthetic registry: only `legacy_retired_col` is retired.
    _write_registry(
        repo_path,
        "surfaces:\n"
        "  - module: legacy_cutover\n"
        "    project: yoke\n"
        "    model: primary\n"
        "    table: projects\n"
        "    column: legacy_retired_col\n",
    )
    rsr.clear_cache()

    return {
        "db_path": tmp_db,
        "checkout_path": repo_path,
        "project": "yoke",
        "audit_db_path": CONNECTED_POSTGRES_AUDIT_TOKEN,
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
        p = _placeholder(conn)
        insert_item(
            conn,
            id=item_id,
            project="yoke",
            status=status,
            db_mutation_profile=json.dumps(profile, sort_keys=True),
        )
        cur = conn.execute(
            "INSERT INTO qa_requirements "
            "(item_id, qa_kind, qa_phase, blocking_mode, "
            " requirement_source, success_policy, created_at) "
            f"VALUES ({p}, 'ac_verification', 'verification', 'blocking', "
            f"        'seeded_default', 'satisfied-by-test', {p}) "
            "RETURNING id",
            (item_id, "2026-04-24T00:00:00Z"),
        )
        req_id = cur.fetchone()[0]
        conn.execute(
            "INSERT INTO qa_runs "
            "(qa_requirement_id, executor_type, qa_kind, verdict, "
            " created_at) "
            f"VALUES ({p}, 'pytest', 'ac_verification', 'pass', {p})",
            (req_id, "2026-04-24T00:00:00Z"),
        )
        conn.commit()
    finally:
        conn.close()


def _advance_status(
    db_path: str,
    item_id: int,
    target: str,
    *,
    repo_path: Path,
) -> dict:
    """Drive the canonical mutator with registry pointer + bypass."""
    import os

    env_patches = {
        "YOKE_DB": db_path,
        "YOKE_CLAIM_BYPASS": "regression-test",
    }
    with mock.patch.dict(os.environ, env_patches, clear=False):
        with _patch_externals(), mock.patch(
            "yoke_core.domain.retired_schema_registry._resolve_registry_path",
            return_value=repo_path
            / "runtime"
            / "api"
            / "domain"
            / "retired_schema_surfaces.yaml",
        ):
            rsr.clear_cache()
            return backlog_updates.execute_update(
                item_id=item_id,
                field="status",
                value=target,
                rebuild_board=False,
            )
