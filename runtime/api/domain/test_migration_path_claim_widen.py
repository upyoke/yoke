"""Atomic migration-territory behavior for ``claims.path.widen``."""

from __future__ import annotations

import copy
import json
from typing import Any

import pytest

from runtime.api.fixtures.backlog import insert_item
from runtime.api.fixtures.file_test_db import connect_test_db, init_test_db
from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)
from yoke_core.domain import coordination_leases, migration_territory_lease
from yoke_core.domain.db_claim import amend
from yoke_core.domain.db_helpers import iso8601_now
from yoke_core.domain.handlers.claims_path import handle_widen
from yoke_core.domain.migration_model_capability import canonical_json
from yoke_core.domain.migration_model_capability_defaults import governed_postgres_seed


YOKE_MODULES = "packages/yoke-core/src/yoke_core/domain/migrations"
EXTERNAL_MODULES = "app/db/migrations"
TEST_LEDGER = {
    "table": "project_migration_history",
    "entry_column": "migration_name",
    "digest_column": "content_sha256",
    "semantics": "membership",
    "serving_floor_column": "minimum_serving_version",
}


@pytest.fixture
def control_conn(tmp_path):
    with init_test_db(tmp_path) as db_path:
        conn = connect_test_db(db_path)
        try:
            yield conn
        finally:
            conn.close()


def _capability(modules_dir: str) -> dict[str, Any]:
    settings = governed_postgres_seed(
        {
            "stack": "test-stack",
            "database_name": "test-db",
            "endpoint_output": "endpoint",
            "secret_arn_output": "secret",
        },
        modules_dir=modules_dir,
        ledger=TEST_LEDGER,
        connection_env_var="TEST_PROJECT_PG_DSN",
    )
    return settings


def _declared_payload(module_name: str) -> dict[str, Any]:
    return {
        "state": "declared",
        "model_name": "primary",
        "mutation_intent": "apply",
        "migration_modules": [module_name],
        "compatibility_class": "pre_merge_safe",
        "migration_strategy": "additive_only",
        "schema_kinds": ["additive"],
        "affected_surfaces": [{"table": "items", "columns": ["title"]}],
        "pre_merge_readers_writers": [
            {"path": "runtime/api/domain/items.py", "role": "writer"}
        ],
        "invariants": ["existing item rows remain readable"],
        "rehearsal_commands": ["python3 -m pytest runtime/api/domain"],
        "residual_risk_notes": "bounded fixture declaration",
    }


def _seed_widen(
    conn: Any,
    *,
    item_id: int,
    project: str,
    modules_dir: str,
    module_name: str,
) -> tuple[int, int]:
    item = insert_item(conn, id=item_id, project=project, status="implementing")
    project_id = int(item["project_id"])
    conn.execute(
        "INSERT INTO project_capabilities (project_id, type, settings, created_at) "
        "VALUES (%s, 'migration_model', %s, %s) "
        "ON CONFLICT (project_id, type) DO UPDATE SET settings = EXCLUDED.settings",
        (project_id, canonical_json(_capability(modules_dir)), iso8601_now()),
    )
    base_id = item_id * 10
    migration_id = base_id + 1
    conn.execute(
        "INSERT INTO path_targets "
        "(id, project_id, kind, path_string, generation, created_at, "
        "materialization_state) VALUES "
        "(%s, %s, 'file', 'src/existing.py', 1, %s, 'observed'), "
        "(%s, %s, 'file', %s, 1, %s, 'observed')",
        (
            base_id,
            project_id,
            iso8601_now(),
            migration_id,
            project_id,
            f"{modules_dir}/{module_name}.py",
            iso8601_now(),
        ),
    )
    claim_id = item_id
    conn.execute(
        "INSERT INTO path_claims "
        "(id, state, mode, owner_kind, owner_item_id, integration_target, "
        "registered_at) VALUES (%s, 'active', 'exclusive', 'item', %s, "
        "'main', %s)",
        (claim_id, item_id, iso8601_now()),
    )
    conn.execute(
        "INSERT INTO path_claim_targets (claim_id, target_id, declared_at) "
        "VALUES (%s, %s, %s)",
        (claim_id, base_id, iso8601_now()),
    )
    conn.commit()
    return claim_id, migration_id


def _request(
    *,
    item_id: int,
    claim_id: int,
    session_id: str,
    target_id: int | None = None,
    add_path: str | None = None,
    db_claim: dict[str, Any] | None = None,
) -> FunctionCallRequest:
    payload: dict[str, Any] = {
        "claim_id": claim_id,
        "reason": "migration implementation expanded",
    }
    if target_id is not None:
        payload["add_target_ids"] = [target_id]
    if add_path is not None:
        payload["add_paths"] = [add_path]
    if db_claim is not None:
        payload["db_claim"] = copy.deepcopy(db_claim)
    return FunctionCallRequest(
        function="claims.path.widen",
        actor=ActorContext(actor_id="operator", session_id=session_id),
        target=TargetRef(kind="item", item_id=item_id),
        payload=payload,
    )


def _stored_claim(conn: Any, item_id: int) -> tuple[dict, dict]:
    row = conn.execute(
        "SELECT db_mutation_profile, db_compatibility_attestation "
        "FROM items WHERE id = %s",
        (item_id,),
    ).fetchone()
    profile = row[0] if isinstance(row[0], dict) else json.loads(row[0])
    attestation = row[1] if isinstance(row[1], dict) else json.loads(row[1])
    return profile, attestation


def _claim_has_target(conn: Any, claim_id: int, target_id: int) -> bool:
    return (
        conn.execute(
            "SELECT 1 FROM path_claim_targets WHERE claim_id = %s AND target_id = %s",
            (claim_id, target_id),
        ).fetchone()
        is not None
    )


def test_atomic_widen_amends_claim_acquires_lease_and_adds_path(control_conn):
    claim_id, target_id = _seed_widen(
        control_conn,
        item_id=4101,
        project="yoke",
        modules_dir=YOKE_MODULES,
        module_name="0006_add_title",
    )
    outcome = handle_widen(
        _request(
            item_id=4101,
            claim_id=claim_id,
            target_id=target_id,
            session_id="scope-owner",
            db_claim=_declared_payload("0006_add_title"),
        )
    )
    assert outcome.primary_success, outcome.error
    assert outcome.result_payload["migration_model"] == "primary"
    profile, attestation = _stored_claim(control_conn, 4101)
    assert profile["migration_modules"] == ["0006_add_title"]
    assert attestation["invariants"] == ["existing item rows remain readable"]
    assert attestation["frozen_at"].endswith("Z")
    assert _claim_has_target(control_conn, claim_id, target_id)
    lease = coordination_leases.active_lease(
        control_conn, "yoke", "LIVE_DB_MIGRATION:primary"
    )
    assert lease is not None and lease.session_id == "scope-owner"
    assert outcome.result_payload["migration_lease_id"] == lease.id


def test_foreign_territory_refusal_rolls_back_claim_and_path(control_conn):
    claim_id, target_id = _seed_widen(
        control_conn,
        item_id=4102,
        project="yoke",
        modules_dir=YOKE_MODULES,
        module_name="0007_foreign_hold",
    )
    held = migration_territory_lease.enter(
        control_conn,
        project="yoke",
        model_name="primary",
        item_id=4199,
        session_id="foreign-owner",
    )
    outcome = handle_widen(
        _request(
            item_id=4102,
            claim_id=claim_id,
            target_id=target_id,
            session_id="scope-owner",
            db_claim=_declared_payload("0007_foreign_hold"),
        )
    )
    assert not outcome.primary_success
    assert "already held" in outcome.error.message
    assert _stored_claim(control_conn, 4102) == ({"state": "none"}, {})
    assert not _claim_has_target(control_conn, claim_id, target_id)
    lease = coordination_leases.active_lease(
        control_conn, "yoke", "LIVE_DB_MIGRATION:primary"
    )
    assert lease is not None and lease.id == held.id
    assert lease.session_id == "foreign-owner"


def test_missing_declaration_refuses_without_partial_state(control_conn):
    claim_id, target_id = _seed_widen(
        control_conn,
        item_id=4103,
        project="yoke",
        modules_dir=YOKE_MODULES,
        module_name="0008_missing_claim",
    )
    outcome = handle_widen(
        _request(
            item_id=4103,
            claim_id=claim_id,
            target_id=target_id,
            session_id="scope-owner",
        )
    )
    assert not outcome.primary_success
    assert "state='declared'" in outcome.error.message
    assert _stored_claim(control_conn, 4103) == ({"state": "none"}, {})
    assert not _claim_has_target(control_conn, claim_id, target_id)
    assert (
        coordination_leases.active_lease(
            control_conn, "yoke", "LIVE_DB_MIGRATION:primary"
        )
        is None
    )


def test_same_session_reuses_existing_migration_territory(control_conn):
    claim_id, target_id = _seed_widen(
        control_conn,
        item_id=4104,
        project="yoke",
        modules_dir=YOKE_MODULES,
        module_name="0009_reused_scope",
    )
    amend(
        4104,
        _declared_payload("0009_reused_scope"),
        reason="migration declared before widening",
        conn=control_conn,
        session_id="scope-owner",
    )
    held = migration_territory_lease.enter(
        control_conn,
        project="yoke",
        model_name="primary",
        item_id=4104,
        session_id="scope-owner",
    )
    outcome = handle_widen(
        _request(
            item_id=4104,
            claim_id=claim_id,
            target_id=target_id,
            session_id="scope-owner",
        )
    )
    assert outcome.primary_success, outcome.error
    assert outcome.result_payload["migration_lease_id"] == held.id
    rows = control_conn.execute(
        "SELECT id FROM coordination_leases "
        "WHERE project_id = 1 AND lease_key = 'LIVE_DB_MIGRATION:primary'"
    ).fetchall()
    assert [int(row[0]) for row in rows] == [held.id]
    assert _claim_has_target(control_conn, claim_id, target_id)


def test_external_project_modules_dir_controls_classification(control_conn):
    claim_id, target_id = _seed_widen(
        control_conn,
        item_id=4105,
        project="externalwebapp",
        modules_dir=EXTERNAL_MODULES,
        module_name="0010_external_schema",
    )
    outcome = handle_widen(
        _request(
            item_id=4105,
            claim_id=claim_id,
            session_id="external-owner",
            add_path=f"{EXTERNAL_MODULES}/0010_external_schema.py",
            db_claim=_declared_payload("0010_external_schema"),
        )
    )
    assert outcome.primary_success, outcome.error
    assert _claim_has_target(control_conn, claim_id, target_id)
    lease = coordination_leases.active_lease(
        control_conn, "externalwebapp", "LIVE_DB_MIGRATION:primary"
    )
    assert lease is not None and lease.project_id == 2
    assert lease.session_id == "external-owner"
    assert (
        coordination_leases.active_lease(
            control_conn, "yoke", "LIVE_DB_MIGRATION:primary"
        )
        is None
    )
