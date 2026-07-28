from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from runtime.api.fixtures.backlog_inserts import insert_item
from yoke_core.domain.builtin_workflow_definitions import (
    BUILTIN_WORKFLOW_IDS,
    builtin_workflow_version_history,
)
from yoke_core.domain.migration_apply_manifest import validate_manifest_payload
from yoke_core.domain.migrations.workflow_item_shape_contract import (
    apply,
    invariants,
)
from yoke_core.domain.schema_common import _column_exists
from yoke_core.domain.workflow_registry import (
    canonical_definition_json,
    definition_digest,
    list_current_workflows,
)

_ROOT = Path(__file__).resolve().parents[4]
_MANIFEST = Path(__file__).with_name("workflow_item_shape_contract.migration.json")


def test_governed_manifest_is_valid_and_digest_bound():
    payload = json.loads(_MANIFEST.read_text(encoding="utf-8"))
    validate_manifest_payload(payload)
    source = payload["module_sources"]["workflow_item_shape_contract"]
    digest = hashlib.sha256((_ROOT / source["path"]).read_bytes()).hexdigest()
    assert digest == source["sha256"]
    affected = {
        row["table"]: set(row["columns"])
        for row in payload["profile"]["affected_surfaces"]
    }
    assert affected["workflows"] == {"current_version_id"}
    assert affected["workflow_versions"] == {
        "workflow_id",
        "version",
        "definition_schema_version",
        "definition_json",
        "definition_digest",
        "published_at",
        "published_by_actor_id",
        "immutable_at",
    }
    assert payload["profile"]["count_preserving"] is False
    assert any(
        "code-owned" in invariant
        for invariant in payload["attestation"]["invariants"]
    )


def _restore_precontract_shape(test_db) -> None:
    test_db.execute("ALTER TABLE items ADD COLUMN type TEXT NOT NULL DEFAULT 'issue'")
    test_db.execute(
        "ALTER TABLE items ADD CONSTRAINT items_type_check "
        "CHECK(type IN ('epic', 'issue'))"
    )
    test_db.execute(
        "ALTER TABLE items ADD CONSTRAINT items_status_check "
        "CHECK(status IN ('idea', 'planned', 'planning', 'implementing'))"
    )
    test_db.execute("ALTER TABLE items ALTER COLUMN status SET DEFAULT 'idea'")
    for column in ("workflow_id", "workflow_version_id"):
        test_db.execute(f"ALTER TABLE items ALTER COLUMN {column} DROP NOT NULL")


def _reset_to_fixed_builtin_history(
    conn,
) -> dict[str, tuple[str, str]]:
    conn.execute(
        "TRUNCATE workflows, workflow_versions RESTART IDENTITY CASCADE"
    )
    expected: dict[str, tuple[str, str]] = {}
    timestamp = "2026-07-25T00:00:00Z"
    for fixture in builtin_workflow_version_history():
        if int(fixture["version"]) != 1:
            continue
        workflow = fixture["workflow"]
        definition = fixture["definition"]
        workflow_id = str(workflow["id"])
        canonical = canonical_definition_json(definition)
        digest = definition_digest(definition)
        expected[workflow_id] = (canonical, digest)
        conn.execute(
            "INSERT INTO workflows "
            "(id, name, description, source, status, created_at, updated_at) "
            "VALUES (%s, %s, %s, %s, 'active', %s, %s)",
            (
                workflow_id,
                workflow["name"],
                workflow["description"],
                workflow["source"],
                timestamp,
                timestamp,
            ),
        )
        version_id = conn.execute(
            "INSERT INTO workflow_versions "
            "(workflow_id, version, definition_schema_version, "
            "definition_json, definition_digest, published_at, immutable_at) "
            "VALUES (%s, 1, 1, %s, %s, %s, %s) RETURNING id",
            (
                workflow_id,
                canonical,
                digest,
                timestamp,
                timestamp,
            ),
        ).fetchone()[0]
        conn.execute(
            "UPDATE workflows SET current_version_id = %s WHERE id = %s",
            (version_id, workflow_id),
        )
    conn.commit()
    return expected


def test_contract_preserves_rows_and_requires_workflow_pins(test_db):
    _restore_precontract_shape(test_db)
    insert_item(test_db, id=711, workflow_id="issue", status="implementing")

    apply(test_db)
    invariants(test_db)

    assert not _column_exists(test_db, "items", "type")
    row = test_db.execute(
        "SELECT workflow_id, status FROM items WHERE id = 711"
    ).fetchone()
    assert tuple(row) == ("issue", "implementing")


def test_contract_appends_current_revisions_without_repinning_launch_items(
    test_db,
):
    _restore_precontract_shape(test_db)
    expected_digests = _reset_to_fixed_builtin_history(test_db)
    insert_item(test_db, id=714, workflow_id="issue", status="idea")
    original_pin = int(
        test_db.execute(
            "SELECT workflow_version_id FROM items WHERE id = 714"
        ).fetchone()[0]
    )
    seeded = test_db.execute(
        "SELECT workflow_id, version, definition_json, definition_digest "
        "FROM workflow_versions ORDER BY workflow_id, version"
    ).fetchall()
    assert len(seeded) == len(BUILTIN_WORKFLOW_IDS)
    assert {
        str(row[0]): (str(row[2]), str(row[3])) for row in seeded
    } == expected_digests
    assert {int(row[1]) for row in seeded} == {1}

    apply(test_db)
    invariants(test_db)

    item_pin = test_db.execute(
        "SELECT i.workflow_version_id, v.version "
        "FROM items i JOIN workflow_versions v ON v.id = i.workflow_version_id "
        "WHERE i.id = 714"
    ).fetchone()
    assert tuple(item_pin) == (original_pin, 1)
    current = list_current_workflows(test_db)
    assert {row["id"] for row in current} == set(BUILTIN_WORKFLOW_IDS)
    assert {row["current_version"] for row in current} == {2}
    assert all(
        [version["version"] for version in row["versions"]] == [1, 2]
        for row in current
    )


def test_contract_refuses_missing_pin(test_db):
    _restore_precontract_shape(test_db)
    insert_item(test_db, id=712, workflow_id="issue", status="idea")
    test_db.execute(
        "UPDATE items SET workflow_id = NULL, workflow_version_id = NULL WHERE id = 712"
    )

    with pytest.raises(AssertionError, match="invalid workflow pins"):
        apply(test_db)


def test_contract_refuses_stage_outside_pinned_definition(test_db):
    _restore_precontract_shape(test_db)
    insert_item(test_db, id=713, workflow_id="issue", status="planning")

    with pytest.raises(AssertionError, match="invalid workflow stages"):
        apply(test_db)
