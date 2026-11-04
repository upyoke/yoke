"""Retroactive gate rejection for item workflow migration."""

from __future__ import annotations

import pytest

from runtime.api.domain.test_workflow_item_migration_compatibility import (
    ITEM_ID,
    _pin,
    _publish_pair,
)
from yoke_core.domain.workflow_definition_codec import WorkflowRegistryError
from yoke_core.domain.workflow_item_versioning import (
    migrate_item_workflow_pin,
)


@pytest.mark.parametrize(
    ("case", "message"),
    (
        ("reached_approval", "unsatisfied approval"),
        ("reached_qa", "unsatisfied QA gate"),
    ),
)
def test_retroactive_gate_without_binding_rejects_migration(
    test_db,
    case: str,
    message: str,
):
    _source, target = _publish_pair(test_db, case=case)
    before = _pin(test_db)

    with pytest.raises(WorkflowRegistryError, match=message):
        migrate_item_workflow_pin(
            test_db,
            item_id=ITEM_ID,
            target_version=int(target["version"]),
        )

    assert _pin(test_db) == before
