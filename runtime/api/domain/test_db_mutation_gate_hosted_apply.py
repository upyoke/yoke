"""Hosted migration evidence must not require a server-side checkout."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from yoke_core.domain import db_mutation_gate_implementing
from yoke_core.domain.db_mutation_gate import (
    check_implementing_to_reviewing_implementation_gate,
)
from runtime.api.domain.db_mutation_gate_test_helpers import (
    _seed_capability,
    _seed_project,
    gate_audit_path,
    gate_db_context,
    seed_audit_row,
)
from yoke_core.domain.retired_schema_registry import load_registry
from runtime.api.fixtures.backlog import insert_item
from runtime.api.fixtures.migration_model_test import governed_postgres_test_seed


@pytest.fixture
def hosted_gate_db(tmp_path: Path):
    with gate_db_context(tmp_path) as (conn, repo_path):
        _seed_project(conn, "yoke", repo_path)
        _seed_capability(conn, "yoke", governed_postgres_test_seed())
        yield conn, repo_path


def _insert_profile(conn, *, item_id: int, intent: str) -> None:
    profile = {
        "state": "declared",
        "model_name": "primary",
        "mutation_intent": intent,
        "migration_modules": ["hosted_receipt"],
        "compatibility_class": "pre_merge_breaking",
    }
    if intent == "apply":
        profile["migration_strategy"] = "additive_only"
    insert_item(
        conn,
        id=item_id,
        project="yoke",
        status="implementing",
        db_mutation_profile=json.dumps(profile, sort_keys=True),
    )


def test_hosted_postgres_apply_uses_receipt_without_checkout(
    hosted_gate_db, monkeypatch: pytest.MonkeyPatch,
) -> None:
    conn, repo_path = hosted_gate_db
    _insert_profile(conn, item_id=7101, intent="apply")
    seed_audit_row(
        repo_path,
        columns="migration_name, state, project_id, model_name, started_at",
        placeholders="?, 'completed', ?, 'primary', ?",
        values=("hosted_receipt", 1, "2026-08-03T00:00:00Z"),
    )
    monkeypatch.setattr(
        db_mutation_gate_implementing,
        "_resolve_repo_path",
        lambda _conn, _project: None,
    )

    outcome = check_implementing_to_reviewing_implementation_gate(
        7101,
        conn=conn,
        audit_db_path=gate_audit_path(repo_path),
    )

    assert outcome.passed, outcome.errors



def test_retired_schema_registry_ships_with_core_package() -> None:
    records = load_registry(force_reload=True)

    assert any(
        record.module == "events_actor_identity"
        and record.table == "events"
        and record.column == "user_id"
        for record in records
    )
