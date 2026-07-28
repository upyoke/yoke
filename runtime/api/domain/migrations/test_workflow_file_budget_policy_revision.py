"""Governed selection of File Budget-aware workflow revisions."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from runtime.api.fixtures.backlog_inserts import insert_item
from yoke_core.domain.migration_apply_manifest import validate_manifest_payload
from yoke_core.domain.migrations.workflow_file_budget_policy_revision import (
    apply,
    invariants,
)
from yoke_core.domain.workflow_registry import list_current_workflows

_ROOT = Path(__file__).resolve().parents[4]
_MANIFEST = Path(__file__).with_name(
    "workflow_file_budget_policy_revision.migration.json"
)


def test_governed_manifest_is_valid_and_digest_bound():
    payload = json.loads(_MANIFEST.read_text(encoding="utf-8"))
    validate_manifest_payload(payload)
    source = payload["module_sources"]["workflow_file_budget_policy_revision"]
    digest = hashlib.sha256((_ROOT / source["path"]).read_bytes()).hexdigest()
    assert digest == source["sha256"]


@pytest.mark.parametrize("starting_version", (1, 2))
def test_revision_selects_v3_without_moving_existing_pins(
    test_db,
    starting_version,
):
    rows = test_db.execute(
        "SELECT workflow_id, id FROM workflow_versions WHERE version = %s",
        (starting_version,),
    ).fetchall()
    for workflow_id, version_id in rows:
        test_db.execute(
            "UPDATE workflows SET current_version_id = %s WHERE id = %s",
            (version_id, workflow_id),
        )
    test_db.commit()
    insert_item(test_db, id=3410 + starting_version, workflow_id="issue")
    before = test_db.execute(
        "SELECT workflow_version_id FROM items WHERE id = %s",
        (3410 + starting_version,),
    ).fetchone()[0]

    apply(test_db)
    invariants(test_db)

    after = test_db.execute(
        "SELECT workflow_version_id FROM items WHERE id = %s",
        (3410 + starting_version,),
    ).fetchone()[0]
    assert int(after) == int(before)
    assert {
        row["current_version"] for row in list_current_workflows(test_db)
    } == {3}


def test_revision_rejects_unknown_selected_definition(test_db):
    changed = test_db.execute(
        "SELECT id FROM workflow_versions "
        "WHERE workflow_id = 'issue' AND version = 3"
    ).fetchone()[0]
    test_db.execute(
        "UPDATE workflows SET current_version_id = %s WHERE id = 'issue'",
        (changed,),
    )
    test_db.commit()

    with pytest.raises(AssertionError, match="not an exact v1/v2"):
        apply(test_db)
