"""Contract tests for workflow-aware backlog item fixtures."""

from __future__ import annotations

import pytest

from runtime.api.fixtures.backlog_inserts import insert_item
from yoke_core.domain.workflow_registry import resolve_current_workflow_pin


@pytest.mark.parametrize(
    ("item_id", "workflow_id", "status"),
    [
        (99001, "issue", "implementing"),
        (99002, "epic", "planning"),
    ],
)
def test_insert_item_pins_selected_workflow_version_and_status(
    test_db,
    item_id: int,
    workflow_id: str,
    status: str,
) -> None:
    expected_workflow_id, expected_version_id = resolve_current_workflow_pin(
        test_db,
        workflow_id,
    )

    row = insert_item(
        test_db,
        id=item_id,
        workflow_id=workflow_id,
        status=status,
    )

    assert row["workflow_id"] == expected_workflow_id
    assert row["workflow_version_id"] == expected_version_id
    assert row["status"] == status
