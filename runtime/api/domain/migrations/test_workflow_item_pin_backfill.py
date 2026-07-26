from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from yoke_core.domain.migration_apply_manifest import validate_manifest_payload
from yoke_core.domain.migrations.workflow_item_pin_backfill import (
    apply,
    invariants,
)
from yoke_core.domain.schema_init import converge_core_schema

_ROOT = Path(__file__).resolve().parents[4]
_MANIFEST = Path(__file__).with_name(
    "workflow_item_pin_backfill.migration.json"
)


def test_governed_manifest_is_valid_and_digest_bound():
    payload = json.loads(_MANIFEST.read_text(encoding="utf-8"))
    validate_manifest_payload(payload)
    source = payload["module_sources"]["workflow_item_pin_backfill"]
    digest = hashlib.sha256(
        (_ROOT / source["path"]).read_bytes()
    ).hexdigest()
    assert digest == source["sha256"]


def _restore_prebackfill_shape(test_db) -> None:
    test_db.execute(
        "ALTER TABLE items ADD COLUMN type TEXT NOT NULL DEFAULT 'issue'"
    )
    for column in ("workflow_id", "workflow_version_id"):
        test_db.execute(
            f"ALTER TABLE items ALTER COLUMN {column} DROP NOT NULL"
        )


def _insert_item(test_db, item_id: int, item_type: str, status: str) -> None:
    test_db.execute(
        "INSERT INTO items "
        "(id, title, type, status, priority, created_at, updated_at, "
        "project_id, project_sequence) "
        "VALUES (%s, %s, %s, %s, 'medium', "
        "'2026-07-25T00:00:00Z', '2026-07-25T00:00:00Z', 1, %s)",
        (item_id, f"Legacy {item_type}", item_type, status, item_id),
    )


def test_backfill_pins_issue_and_epic_without_changing_stage(test_db):
    _restore_prebackfill_shape(test_db)
    _insert_item(test_db, 701, "issue", "implementing")
    _insert_item(test_db, 702, "epic", "planned")

    apply(test_db)
    invariants(test_db)

    rows = test_db.execute(
        "SELECT id, type, status, workflow_id, workflow_version_id "
        "FROM items WHERE id IN (701, 702) ORDER BY id"
    ).fetchall()
    assert [tuple(row[:4]) for row in rows] == [
        (701, "issue", "implementing", "issue"),
        (702, "epic", "planned", "epic"),
    ]
    assert all(int(row[4]) > 0 for row in rows)


def test_backfill_refuses_partial_pin(test_db):
    _restore_prebackfill_shape(test_db)
    _insert_item(test_db, 703, "issue", "idea")
    test_db.execute(
        "UPDATE items SET workflow_id = 'issue' WHERE id = 703"
    )

    with pytest.raises(RuntimeError, match="partial workflow pins"):
        apply(test_db)


def test_boot_convergence_backfills_legacy_items_before_readers_serve(test_db):
    _restore_prebackfill_shape(test_db)
    _insert_item(test_db, 705, "issue", "implementing")
    _insert_item(test_db, 706, "epic", "planned")

    converge_core_schema(test_db)

    rows = test_db.execute(
        "SELECT id, workflow_id, workflow_version_id "
        "FROM items WHERE id IN (705, 706) ORDER BY id"
    ).fetchall()
    assert [(row[0], row[1]) for row in rows] == [
        (705, "issue"),
        (706, "epic"),
    ]
    assert all(int(row[2]) > 0 for row in rows)


def test_invariant_refuses_stage_outside_pinned_definition(test_db):
    _restore_prebackfill_shape(test_db)
    _insert_item(test_db, 704, "issue", "planning")
    apply(test_db)

    with pytest.raises(AssertionError, match="is not valid"):
        invariants(test_db)
