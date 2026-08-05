"""Coverage for the stage-vocabulary entry in the migration history."""

from __future__ import annotations

import json
import sqlite3

import pytest

from yoke_core.domain import migrations as migration_history_package
from yoke_core.domain.migration_history import (
    history_dir,
    load_migration_module,
    ordered_entries,
)
from yoke_core.domain.workflow_definition_codec import definition_digest
from yoke_core.domain.workflow_schema import _ensure_immutable_version_triggers

# History entries are named ``NNNN_slug``, which is not an importable
# identifier, so the module loads through the history loader the applier
# itself uses. Selecting by slug rather than by full name keeps this test
# working across a renumbering (a squash renumbers; it does not rename).
_ENTRY_SLUG = "workflow_and_deployment_stage_vocabulary"
_entry = next(
    entry
    for entry in ordered_entries(history_dir(migration_history_package))
    if entry.name.endswith(_ENTRY_SLUG)
)
migration = load_migration_module(_entry.path, _entry.name)


def _connection() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    # The per-workflow digest uniqueness is part of the fixture because it is
    # the guarantee this entry has to write within: without it a rewrite that
    # recreates an existing row passes here and fails on a real universe.
    conn.execute(
        "CREATE TABLE workflow_versions ("
        "id INTEGER PRIMARY KEY, workflow_id TEXT NOT NULL, "
        "version INTEGER NOT NULL, definition_json TEXT NOT NULL, "
        "definition_digest TEXT NOT NULL, "
        "definition_schema_version INTEGER NOT NULL, "
        "UNIQUE(workflow_id, definition_digest))"
    )
    conn.execute(
        "CREATE TABLE deployment_flows ("
        "id TEXT PRIMARY KEY, stages TEXT NOT NULL)"
    )
    _ensure_immutable_version_triggers(conn)
    return conn


def _insert(
    conn: sqlite3.Connection,
    row_id: int,
    definition: dict,
    schema_version: int,
    *,
    workflow_id: str = "issue",
    version: int | None = None,
) -> None:
    conn.execute(
        "INSERT INTO workflow_versions (id, workflow_id, version, "
        "definition_json, definition_digest, definition_schema_version) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (
            row_id,
            workflow_id,
            row_id if version is None else version,
            json.dumps(definition),
            definition_digest(definition),
            schema_version,
        ),
    )


def _migrated(definition: dict) -> dict:
    """The same definition as the registry publishes it after the cutover."""
    published = json.loads(json.dumps(definition))
    published["schema_version"] = 3
    published["skill_bindings"] = published.pop("executor_bindings")
    published["skill_bindings"][0]["skill_id"] = published["skill_bindings"][0].pop(
        "executor_id"
    )
    for stage in published["stages"]:
        if isinstance(stage.get("description"), str):
            stage["description"] = stage["description"].replace("executor", "skill")
    return published


def _legacy_workflow() -> dict:
    return {
        "schema_version": 2,
        "stages": [
            {
                "id": "idea",
                "description": "The executor owns this stage.",
            },
            {"id": "done"},
        ],
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
    _insert(conn, 1, definition, 2)
    conn.execute(
        "INSERT INTO deployment_flows VALUES (?, ?)",
        (
            "release",
            # No retired kind-shaped stage here: the entry that strips those
            # runs earlier in the history, so by the time this one revalidates
            # a flow's stages they are gone.
            json.dumps([{"name": "merged", "executor": "auto"}]),
        ),
    )

    migration.apply(conn)
    migration.invariants(conn)

    with pytest.raises(sqlite3.IntegrityError, match="immutable"):
        conn.execute(
            "UPDATE workflow_versions SET definition_json='{}' WHERE id=1"
        )

    stored = json.loads(
        conn.execute(
            "SELECT definition_json FROM workflow_versions WHERE id=1"
        ).fetchone()[0]
    )
    assert stored["schema_version"] == 3
    assert stored["skill_bindings"][0]["skill_id"] == "dash"
    assert stored["stages"][0]["description"] == "The skill owns this stage."
    assert "executor_bindings" not in stored
    assert conn.execute(
        "SELECT definition_schema_version FROM workflow_versions WHERE id=1"
    ).fetchone()[0] == 3
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
    _insert(conn, 1, definition, 2)

    with pytest.raises(AssertionError, match="both binding vocabularies"):
        migration.apply(conn)


def test_migration_no_ops_on_definitions_past_its_target_version() -> None:
    # A permanent history entry outlives the shape it was written against.
    # This one moved definitions from 2 to 3; the codec has since gone to 4,
    # and every boot converges built-in definitions at the current version
    # BEFORE the history runs. Treating "newer than my target" as an error
    # made this entry crash every boot on every universe -- the entry had not
    # become wrong, it had become finished.
    conn = _connection()
    definition = _legacy_workflow()
    definition["schema_version"] = 4
    definition["skill_bindings"] = definition.pop("executor_bindings")
    definition["skill_bindings"][0]["skill_id"] = definition["skill_bindings"][
        0
    ].pop("executor_id")
    _insert(conn, 1, definition, 4)

    migration.apply(conn)
    migration.invariants(conn)

    stored = json.loads(
        conn.execute(
            "SELECT definition_json FROM workflow_versions WHERE id=1"
        ).fetchone()[0]
    )
    assert stored["schema_version"] == 4, "a later version must be left alone"
    assert stored["skill_bindings"][0]["skill_id"] == "dash"


def test_migration_leaves_already_migrated_rows_byte_identical() -> None:
    # These are published immutable definitions, and this entry disables their
    # immutability trigger to touch them. Re-serializing a row that already
    # carries the new vocabulary would recompute its digest for no reason, and
    # a published definition whose digest stops matching the code-owned one is
    # a startup abort. So an entry that is already done must write nothing.
    conn = _connection()
    definition = _legacy_workflow()
    _insert(conn, 1, definition, 2)
    conn.execute(
        "INSERT INTO deployment_flows VALUES (?, ?)",
        ("release", json.dumps([{"name": "merged", "step_runner": "auto"}])),
    )
    migration.apply(conn)

    before = conn.execute(
        "SELECT definition_json, definition_digest FROM workflow_versions "
        "WHERE id=1"
    ).fetchone()
    flow_before = conn.execute(
        "SELECT stages FROM deployment_flows WHERE id='release'"
    ).fetchone()[0]

    # Second run: the immutability trigger is live again, so a write here
    # would raise rather than silently churn the digest.
    migration.apply(conn)

    after = conn.execute(
        "SELECT definition_json, definition_digest FROM workflow_versions "
        "WHERE id=1"
    ).fetchone()
    flow_after = conn.execute(
        "SELECT stages FROM deployment_flows WHERE id='release'"
    ).fetchone()[0]
    assert tuple(after) == tuple(before)
    assert flow_after == flow_before


def test_migration_preserves_historical_workflow_schema() -> None:
    conn = _connection()
    definition = _legacy_workflow()
    definition["schema_version"] = 1
    _insert(conn, 1, definition, 1)

    migration.apply(conn)
    migration.invariants(conn)

    stored = json.loads(
        conn.execute(
            "SELECT definition_json FROM workflow_versions WHERE id=1"
        ).fetchone()[0]
    )
    assert stored["schema_version"] == 1
    assert stored["skill_bindings"][0]["skill_id"] == "dash"


def test_migration_folds_a_row_the_registry_already_republished() -> None:
    # The registry publishes a new version whenever the code-owned definition
    # changes, so the rename this entry performs can already have been
    # published as its own row while the entry sat unapplied. Rewriting the
    # older row then recreates the newer one, and a workflow may not carry one
    # digest twice. Neither referencing table exists here, which is also the
    # state of a universe that has not created them yet.
    conn = _connection()
    legacy = _legacy_workflow()
    _insert(conn, 9, legacy, 2, version=3)
    _insert(conn, 15, _migrated(legacy), 3, version=4)

    migration.apply(conn)
    migration.invariants(conn)

    rows = conn.execute(
        "SELECT id, version FROM workflow_versions ORDER BY version"
    ).fetchall()
    assert rows == [(15, 4)], "the newer row survives and the duplicate folds"


def test_fold_carries_references_onto_the_surviving_row() -> None:
    conn = _connection()
    conn.execute(
        "CREATE TABLE items (id INTEGER PRIMARY KEY, workflow_version_id INTEGER)"
    )
    conn.execute(
        "CREATE TABLE decision_requests ("
        "id INTEGER PRIMARY KEY, consumed_workflow_version_id INTEGER)"
    )
    legacy = _legacy_workflow()
    _insert(conn, 9, legacy, 2, version=3)
    _insert(conn, 15, _migrated(legacy), 3, version=4)
    conn.execute("INSERT INTO items VALUES (1, 9)")
    conn.execute("INSERT INTO decision_requests VALUES (1, 9)")

    migration.apply(conn)

    assert conn.execute("SELECT workflow_version_id FROM items").fetchone()[0] == 15
    assert (
        conn.execute(
            "SELECT consumed_workflow_version_id FROM decision_requests"
        ).fetchone()[0]
        == 15
    )


def test_fold_keeps_versions_of_different_workflows_apart() -> None:
    # Uniqueness is per workflow, so two workflows legitimately share a
    # definition. Folding across them would delete a live workflow's only row.
    conn = _connection()
    legacy = _legacy_workflow()
    _insert(conn, 1, legacy, 2, workflow_id="issue", version=1)
    _insert(conn, 2, legacy, 2, workflow_id="epic", version=1)

    migration.apply(conn)
    migration.invariants(conn)

    assert conn.execute(
        "SELECT COUNT(*) FROM workflow_versions"
    ).fetchone()[0] == 2
