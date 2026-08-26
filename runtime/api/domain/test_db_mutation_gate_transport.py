"""Transport-boundary coverage for the idea-stage DB-mutation gate."""

from __future__ import annotations

import json
from pathlib import Path
from unittest import mock

import pytest

from runtime.api.api_items_test_helpers import _client_for_db
from runtime.api.domain.db_mutation_gate_test_helpers import (
    _seed_capability,
    _seed_project,
    _write_module,
    gate_db_context,
)
from runtime.api.fixtures.backlog import insert_item
from runtime.api.fixtures.migration_model_test import (
    TEST_MIGRATION_MODULES_DIR,
    governed_postgres_test_seed,
)
from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)
from yoke_core.domain import db_backend
from yoke_core.domain import db_mutation_gate_idea as idea_gate
from yoke_core.domain import yoke_function_dispatch as dispatch_module
from yoke_core.domain import yoke_function_dispatch_claims as claims_module
from yoke_core.domain import yoke_function_dispatch_events as events_module
from yoke_core.domain.handlers.lifecycle_transition import (
    REGISTRATIONS as LIFECYCLE_REGISTRATIONS,
)
from yoke_core.domain.handlers.lifecycle_transition import handle_transition
from yoke_core.domain.handlers.items_scalar import (
    REGISTRATIONS as SCALAR_REGISTRATIONS,
)
from yoke_core.domain.yoke_function_registry import (
    register,
    reset_registry_for_tests,
)
from yoke_core.domain.work_claim_targets import make_item_target


SESSION_ID = "db-gate-transport-session"
ITEM_ID = 4242


@pytest.fixture
def gate_db(tmp_path: Path):
    with gate_db_context(tmp_path) as context:
        yield context


@pytest.fixture
def registered_status_handlers():
    reset_registry_for_tests()
    for entry in (*LIFECYCLE_REGISTRATIONS, *SCALAR_REGISTRATIONS):
        register(**entry)
    with (
        mock.patch.object(events_module, "emit_event"),
        mock.patch.object(
            dispatch_module,
            "_idempotency_lookup",
            return_value=None,
        ),
    ):
        yield
    reset_registry_for_tests()


def _profile(*, compatibility_class: str = "pre_merge_breaking") -> dict:
    return {
        "state": "declared",
        "model_name": "primary",
        "mutation_intent": "apply",
        "migration_modules": ["transport_probe"],
        "compatibility_class": compatibility_class,
        "migration_strategy": "additive_only",
    }


def _attestation() -> dict:
    return {
        "pre_merge_readers_writers": [
            {"path": "app/model.py", "symbol": "load", "role": "reader"},
        ],
        "invariants": ["existing readers tolerate additive changes"],
        "rehearsal_commands": ["pytest -q"],
        "residual_risk_notes": "The new surface is additive.",
    }


def _stage(
    gate_db,
    *,
    profile: dict | None = None,
    attestation: dict | None = None,
) -> tuple[object, Path]:
    conn, repo_path = gate_db
    _seed_project(conn, "yoke", repo_path)
    _seed_capability(conn, "yoke", governed_postgres_test_seed())
    insert_item(
        conn,
        id=ITEM_ID,
        project="yoke",
        workflow_id="issue",
        status="idea",
        db_mutation_profile=json.dumps(profile or _profile(), sort_keys=True),
        db_compatibility_attestation=json.dumps(
            attestation or {},
            sort_keys=True,
        ),
    )
    return conn, repo_path


def _seed_work_claim(conn) -> None:
    marker = "%s" if db_backend.connection_is_postgres(conn) else "?"
    target = make_item_target(ITEM_ID)
    conn.execute(
        "INSERT INTO work_claims "
        "(session_id, target_kind, scope, claim_type, claimed_at, "
        "last_heartbeat) "
        f"VALUES ({marker}, {marker}, {marker}, 'exclusive', "
        f"{marker}, {marker})",
        (
            SESSION_ID,
            target.kind,
            target.scope_json(),
            "2026-08-22T00:00:00Z",
            "2026-08-22T00:00:00Z",
        ),
    )
    conn.commit()


def _request() -> FunctionCallRequest:
    return FunctionCallRequest(
        function="lifecycle.transition.execute",
        actor=ActorContext(actor_id="op", session_id=SESSION_ID),
        target=TargetRef(kind="item", item_id=ITEM_ID, item_ref="YOK-4242"),
        payload={
            "source_status": "idea",
            "target_status": "refining-idea",
            "reason": "transport-boundary verification",
        },
    )


def _scalar_request() -> FunctionCallRequest:
    return FunctionCallRequest(
        function="items.scalar.update",
        actor=ActorContext(actor_id="op", session_id=SESSION_ID),
        target=TargetRef(kind="item", item_id=ITEM_ID, item_ref="YOK-4242"),
        payload={"field": "status", "value": "refining-idea"},
    )


def test_relayed_gate_passes_and_reports_checkout_dependent_scan_skip(
    gate_db,
) -> None:
    conn, _repo_path = _stage(gate_db)
    with mock.patch.object(idea_gate, "_resolve_repo_path", return_value=None):
        outcome = idea_gate.check_idea_to_refining_idea_gate(ITEM_ID, conn=conn)

    assert outcome.passed, outcome.errors
    assert outcome.warnings == [
        "mechanical DDL scan skipped: project 'yoke' has no machine-local "
        "checkout on this execution host"
    ]


def test_db_sourced_modules_dir_validation_runs_without_checkout(gate_db) -> None:
    conn, _repo_path = _stage(gate_db)
    settings = governed_postgres_test_seed()
    del settings["models"]["primary"]["runner"]["config"]["modules_dir"]
    with (
        mock.patch.object(
            idea_gate,
            "_load_capability_settings",
            return_value=settings,
        ),
        mock.patch.object(idea_gate, "_resolve_repo_path", return_value=None),
    ):
        outcome = idea_gate.check_idea_to_refining_idea_gate(ITEM_ID, conn=conn)

    assert not outcome.passed
    assert any("runner.config.modules_dir missing" in error for error in outcome.errors)


def test_external_adapter_remains_rejected_without_checkout(gate_db) -> None:
    conn, _repo_path = _stage(gate_db)
    settings = governed_postgres_test_seed()
    settings["models"]["primary"]["runner"] = {
        "kind": "external_adapter",
        "config": {},
    }
    with (
        mock.patch.object(
            idea_gate,
            "_load_capability_settings",
            return_value=settings,
        ),
        mock.patch.object(idea_gate, "_resolve_repo_path", return_value=None),
    ):
        outcome = idea_gate.check_idea_to_refining_idea_gate(ITEM_ID, conn=conn)

    assert not outcome.passed
    assert any(
        "external_adapter runners are reserved" in error for error in outcome.errors
    )


def test_local_gate_still_scans_existing_migration_module(gate_db) -> None:
    conn, repo_path = _stage(
        gate_db,
        profile=_profile(compatibility_class="pre_merge_safe"),
        attestation=_attestation(),
    )
    _write_module(
        repo_path,
        TEST_MIGRATION_MODULES_DIR,
        "transport_probe",
        body="MIGRATION = '''\nDROP TABLE stale_data;\n'''\n",
    )

    outcome = idea_gate.check_idea_to_refining_idea_gate(ITEM_ID, conn=conn)

    assert not outcome.passed
    assert any("scanner banned-pattern" in error for error in outcome.errors)
    assert outcome.warnings == []


@pytest.mark.parametrize(
    "request_factory",
    (_request, _scalar_request),
    ids=("lifecycle-transition", "scalar-status-update"),
)
def test_http_status_adapters_surface_the_relayed_scan_warning(
    gate_db,
    registered_status_handlers,
    request_factory,
) -> None:
    conn, repo_path = _stage(gate_db)
    _seed_work_claim(conn)
    envelope = request_factory().model_dump(mode="json")
    claim = {"id": 1, "session_id": SESSION_ID}
    with (
        mock.patch.object(idea_gate, "_resolve_repo_path", return_value=None),
        mock.patch.object(
            claims_module,
            "who_claims_for_item",
            return_value=claim,
        ),
        _client_for_db(str(repo_path / "yoke.db")) as client,
    ):
        response = client.post("/v1/functions/call", json=envelope)

    assert response.status_code == 207, response.text
    body = response.json()
    assert body["success"], body
    assert body["result"].get("to_status", body["result"].get("value")) == (
        "refining-idea"
    )
    assert body["warnings"] == [
        {
            "code": "db_mutation_check_skipped",
            "step": "mechanical_ddl_scan",
            "detail": (
                "mechanical DDL scan skipped: project 'yoke' has no "
                "machine-local checkout on this execution host"
            ),
            "recovery_function": None,
        }
    ]


def test_local_transition_reports_no_scan_warning(gate_db) -> None:
    conn, repo_path = _stage(gate_db)
    _seed_work_claim(conn)
    _write_module(
        repo_path,
        TEST_MIGRATION_MODULES_DIR,
        "transport_probe",
        body="MIGRATION = '''\nCREATE TABLE demo (id INTEGER);\n'''\n",
    )

    outcome = handle_transition(_request())

    assert outcome.primary_success, outcome.error
    assert outcome.result_payload["to_status"] == "refining-idea"
    assert outcome.warnings == []
