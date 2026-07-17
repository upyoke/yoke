"""Table-level destructive post-state tests for db_mutation_gate."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from yoke_core.domain import retired_schema_registry as rsr
from yoke_core.domain.db_mutation_gate import (
    check_implementing_to_reviewing_implementation_gate,
)
from runtime.api.fixtures.migration_model_test import governed_postgres_test_seed
from yoke_core.domain.db_mutation_gate_test_helpers import (
    _seed_capability,
    _seed_flow_with_migration_apply,
    _seed_project,
    _write_module,
    create_table_on_audit_db,
    gate_audit_path,
    seed_audit_row,
)
from runtime.api.domain.test_db_mutation_gate_evidence import gate_db  # noqa: F401 — pytest fixture
from runtime.api.fixtures.backlog import insert_item


@pytest.fixture(autouse=True)
def _clear_cache() -> None:
    rsr.clear_cache()
    yield
    rsr.clear_cache()


def _audit_path(gate_db) -> str:
    # The gate's items+audit database is one per-test DB (gate_db_context);
    # migration_audit already exists there. The returned token matches
    # init_test_db's db_path so the gate's own connection lands on the same DB.
    _conn, repo_path = gate_db
    return gate_audit_path(repo_path)


def _stage_apply_with_table_surface(
    gate_db,
    identifier: str,
    table_name: str,
) -> int:
    conn, repo_path = gate_db
    _seed_project(conn, "yoke", repo_path)
    _seed_capability(conn, "yoke", governed_postgres_test_seed())
    _seed_flow_with_migration_apply(conn, "yoke")
    _write_module(repo_path, "runtime/api/domain/migrations", identifier)
    profile = {
        "state": "declared",
        "model_name": "primary",
        "mutation_intent": "apply",
        "migration_modules": [identifier],
        "compatibility_class": "pre_merge_safe",
        "migration_strategy": "additive_only",
        "schema_kinds": ["destructive"],
        "data_kinds": ["drop"],
        "affected_surfaces": [{"table": table_name}],
        "count_preserving": False,
    }
    item_id = 5151
    insert_item(
        conn, id=item_id, project="yoke", status="implementing",
        db_mutation_profile=json.dumps(profile, sort_keys=True),
    )
    return item_id


def _seed_completed_audit(repo_path: Path, identifier: str) -> None:
    seed_audit_row(
        repo_path,
        columns="migration_name, state, project_id, model_name, started_at",
        placeholders="?, 'completed', ?, 'primary', ?",
        values=(identifier, 1, "2026-04-25T00:00:00Z"),
    )


def _write_table_registry(
    repo_path: Path,
    table_name: str,
    module: str,
) -> None:
    target = repo_path / "runtime" / "api" / "domain" / "retired_schema_surfaces.yaml"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        "surfaces:\n"
        f"  - module: {module}\n"
        "    project: yoke\n"
        "    model: primary\n"
        f"    table: {table_name}\n",
        encoding="utf-8",
    )
    rsr.clear_cache()


def test_table_level_post_state_drift_blocks(gate_db) -> None:
    conn, repo_path = gate_db
    item_id = _stage_apply_with_table_surface(
        gate_db, "drop_demo_backup", "demo_backup",
    )
    audit_path = _audit_path(gate_db)
    _seed_completed_audit(repo_path, "drop_demo_backup")
    create_table_on_audit_db(
        repo_path,
        "CREATE TABLE demo_backup (id INTEGER PRIMARY KEY, payload TEXT)",
    )
    _write_table_registry(repo_path, "demo_backup", "drop_demo_backup")
    outcome = check_implementing_to_reviewing_implementation_gate(
        item_id, conn=conn, audit_db_path=audit_path,
    )
    assert not outcome.passed
    assert any(
        "table 'demo_backup' is still present" in e
        for e in outcome.errors
    )
    assert any("drop_demo_backup" in e for e in outcome.errors)


def test_table_level_post_state_clean_passes(gate_db) -> None:
    conn, repo_path = gate_db
    item_id = _stage_apply_with_table_surface(
        gate_db, "drop_demo_backup", "demo_backup",
    )
    audit_path = _audit_path(gate_db)
    _seed_completed_audit(repo_path, "drop_demo_backup")
    _write_table_registry(repo_path, "demo_backup", "drop_demo_backup")
    outcome = check_implementing_to_reviewing_implementation_gate(
        item_id, conn=conn, audit_db_path=audit_path,
    )
    assert outcome.passed, outcome.errors


def test_table_level_unregistered_surface_does_not_block(gate_db) -> None:
    conn, repo_path = gate_db
    item_id = _stage_apply_with_table_surface(
        gate_db, "drop_demo_backup", "demo_backup",
    )
    audit_path = _audit_path(gate_db)
    _seed_completed_audit(repo_path, "drop_demo_backup")
    create_table_on_audit_db(
        repo_path,
        "CREATE TABLE demo_backup (id INTEGER PRIMARY KEY)",
    )
    target = repo_path / "runtime" / "api" / "domain" / "retired_schema_surfaces.yaml"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("surfaces: []\n", encoding="utf-8")
    rsr.clear_cache()
    outcome = check_implementing_to_reviewing_implementation_gate(
        item_id, conn=conn, audit_db_path=audit_path,
    )
    assert outcome.passed, outcome.errors
