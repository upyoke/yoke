from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from runtime.api.fixtures.backlog_inserts import insert_item
from yoke_core.domain.migration_apply_manifest import validate_manifest_payload
from yoke_core.domain.migrations.workflow_item_browser_qa_metadata_contract import (
    apply,
    invariants,
)
from yoke_core.domain.schema_common import _column_exists

_ROOT = Path(__file__).resolve().parents[4]
_MANIFEST = Path(__file__).with_name(
    "workflow_item_browser_qa_metadata_contract.migration.json"
)


def test_governed_manifest_is_valid_and_digest_bound():
    payload = json.loads(_MANIFEST.read_text(encoding="utf-8"))
    validate_manifest_payload(payload)
    source = payload["module_sources"][
        "workflow_item_browser_qa_metadata_contract"
    ]
    digest = hashlib.sha256((_ROOT / source["path"]).read_bytes()).hexdigest()
    assert digest == source["sha256"]


def _restore_metadata_column(test_db) -> None:
    test_db.execute(
        "ALTER TABLE items ADD COLUMN browser_qa_metadata JSONB "
        "NOT NULL DEFAULT '{}'::jsonb"
    )


def _set_browser_metadata(test_db, item_id: int) -> None:
    test_db.execute(
        "UPDATE items SET browser_qa_metadata=%s WHERE id=%s",
        (
            json.dumps({
                "browser_testable": True,
                "visual_outcome": True,
                "browser_routes": ["/workflows"],
                "browser_timing_hints_ms": [],
            }),
            item_id,
        ),
    )


def test_contract_drops_metadata_after_active_item_parity(test_db):
    _restore_metadata_column(test_db)
    insert_item(test_db, id=721, workflow_id="issue", status="implementing")
    _set_browser_metadata(test_db, 721)
    test_db.execute(
        "INSERT INTO qa_requirements("
        "item_id, qa_kind, qa_phase, blocking_mode, requirement_source, "
        "method_id, created_at"
        ") VALUES (721, 'plan_case', 'verification', 'blocking', "
        "'flow_derived', 'browser-inspection', CURRENT_TIMESTAMP)"
    )

    apply(test_db)
    invariants(test_db)

    assert not _column_exists(test_db, "items", "browser_qa_metadata")
    assert test_db.execute("SELECT COUNT(*) FROM items").fetchone()[0] >= 1


def test_contract_refuses_active_item_without_browser_qa(test_db):
    _restore_metadata_column(test_db)
    insert_item(test_db, id=722, workflow_id="issue", status="implementing")
    _set_browser_metadata(test_db, 722)

    with pytest.raises(AssertionError, match="lack materialized Browser QA"):
        apply(test_db)


def test_contract_allows_terminal_item_without_new_requirement(test_db):
    _restore_metadata_column(test_db)
    insert_item(test_db, id=723, workflow_id="issue", status="done")
    _set_browser_metadata(test_db, 723)

    apply(test_db)
    invariants(test_db)

    assert not _column_exists(test_db, "items", "browser_qa_metadata")
