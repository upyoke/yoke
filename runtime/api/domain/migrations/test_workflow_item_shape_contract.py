from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from runtime.api.fixtures.backlog_inserts import insert_item
from yoke_core.domain.migration_apply_manifest import validate_manifest_payload
from yoke_core.domain.migrations.workflow_item_shape_contract import (
    apply,
    invariants,
)
from yoke_core.domain.schema_common import _column_exists

_ROOT = Path(__file__).resolve().parents[4]
_MANIFEST = Path(__file__).with_name("workflow_item_shape_contract.migration.json")


def test_governed_manifest_is_valid_and_digest_bound():
    payload = json.loads(_MANIFEST.read_text(encoding="utf-8"))
    validate_manifest_payload(payload)
    source = payload["module_sources"]["workflow_item_shape_contract"]
    digest = hashlib.sha256((_ROOT / source["path"]).read_bytes()).hexdigest()
    assert digest == source["sha256"]


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
