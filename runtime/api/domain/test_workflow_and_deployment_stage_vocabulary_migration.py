"""Coverage for the retained stage-vocabulary data migration."""

from __future__ import annotations

import json
import sqlite3

import pytest

from yoke_core.domain.migrations import workflow_and_deployment_stage_vocabulary as migration
from yoke_core.domain.workflow_definition_codec import definition_digest


def _connection() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.execute(
        "CREATE TABLE workflow_versions ("
        "id INTEGER PRIMARY KEY, definition_json TEXT NOT NULL, "
        "definition_digest TEXT NOT NULL)"
    )
    conn.execute(
        "CREATE TABLE deployment_flows ("
        "id TEXT PRIMARY KEY, stages TEXT NOT NULL)"
    )
    return conn


def _legacy_workflow() -> dict:
    return {
        "schema_version": 2,
        "stages": [{"id": "idea"}, {"id": "done"}],
        "terminal_stage_ids": ["done"],
        "transitions": [{"from_stage_id": "idea", "to_stage_id": "done"}],
        "entry_surfaces": ["harness_skill"],
        "executor_bindings": [
            {
                "executor_id": "dash",
                "from_stage_id": "idea",
                "through_stage_id": "done",
            }
        ],
        "policies": {},
    }


def test_migration_rewrites_keys_and_preserves_rows() -> None:
    conn = _connection()
    definition = _legacy_workflow()
    conn.execute(
        "INSERT INTO workflow_versions VALUES (?, ?, ?)",
        (1, json.dumps(definition), definition_digest(definition)),
    )
    conn.execute(
        "INSERT INTO deployment_flows VALUES (?, ?)",
        (
            "release",
            json.dumps(
                [
                    {"name": "merged", "executor": "auto"},
                    {
                        "kind": "migration_apply",
                        "model_name": "primary",
                        "lifecycle_phase": "implementing",
                    },
                ]
            ),
        ),
    )

    migration.apply(conn)
    migration.invariants(conn)

    stored = json.loads(
        conn.execute(
            "SELECT definition_json FROM workflow_versions WHERE id=1"
        ).fetchone()[0]
    )
    assert stored["schema_version"] == 3
    assert stored["skill_bindings"][0]["skill_id"] == "dash"
    assert "executor_bindings" not in stored
    stages = json.loads(
        conn.execute(
            "SELECT stages FROM deployment_flows WHERE id='release'"
        ).fetchone()[0]
    )
    assert stages[0]["step_runner"] == "auto"
    assert conn.execute("SELECT COUNT(*) FROM workflow_versions").fetchone()[0] == 1
    assert conn.execute("SELECT COUNT(*) FROM deployment_flows").fetchone()[0] == 1

    migration.apply(conn)
    migration.invariants(conn)


def test_migration_rejects_mixed_vocabulary() -> None:
    conn = _connection()
    definition = _legacy_workflow()
    definition["skill_bindings"] = []
    conn.execute(
        "INSERT INTO workflow_versions VALUES (?, ?, ?)",
        (1, json.dumps(definition), definition_digest(definition)),
    )

    with pytest.raises(AssertionError, match="both binding vocabularies"):
        migration.apply(conn)


def test_migration_preserves_historical_workflow_schema() -> None:
    conn = _connection()
    definition = _legacy_workflow()
    definition["schema_version"] = 1
    conn.execute(
        "INSERT INTO workflow_versions VALUES (?, ?, ?)",
        (1, json.dumps(definition), definition_digest(definition)),
    )

    migration.apply(conn)
    migration.invariants(conn)

    stored = json.loads(
        conn.execute(
            "SELECT definition_json FROM workflow_versions WHERE id=1"
        ).fetchone()[0]
    )
    assert stored["schema_version"] == 1
    assert stored["skill_bindings"][0]["skill_id"] == "dash"
