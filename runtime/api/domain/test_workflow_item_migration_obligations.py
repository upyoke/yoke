"""Path-claim and worktree obligations introduced by workflow migration."""

from __future__ import annotations

from runtime.api.domain.workflow_item_migration_obligations_test_support import (
    _publish_policy_pair as _publish_policy_pair,
)


import pytest

from runtime.api.domain.workflow_item_migration_compatibility_test_support import (
    ITEM_ID,
    _pin,
    _seed_path_claim,
)
from runtime.api.fixtures.backlog_inserts import insert_epic_task
from runtime.api.task_files_touched_test_support import declare_task_files
from yoke_core.domain.workflow_definition_builders import (
    WORKFLOW_FILE_BUDGET_OPTIONAL,
    WORKFLOW_FILE_BUDGET_REQUIRED,
    WORKFLOW_FILE_BUDGET_REQUIRED_PER_TASK,
    WORKFLOW_PATH_CLAIMS_OPTIONAL,
    WORKFLOW_PATH_CLAIMS_REQUIRED,
    WORKFLOW_PATH_CLAIMS_REQUIRED_PER_TASK,
)
from yoke_core.domain.workflow_definition_codec import WorkflowRegistryError
from yoke_core.domain.workflow_item_versioning import (
    migrate_item_workflow_pin,
)


def test_new_required_file_budget_rejects_missing_current_coverage(test_db):
    _source, target = _publish_policy_pair(
        test_db,
        source_file_budget=WORKFLOW_FILE_BUDGET_OPTIONAL,
        target_file_budget=WORKFLOW_FILE_BUDGET_REQUIRED,
    )
    before = _pin(test_db)

    with pytest.raises(WorkflowRegistryError, match="File Budget policy"):
        migrate_item_workflow_pin(
            test_db,
            item_id=ITEM_ID,
            target_version=int(target["version"]),
        )

    assert _pin(test_db) == before


def test_new_required_file_budget_accepts_resolved_current_budget(test_db):
    _source, target = _publish_policy_pair(
        test_db,
        source_file_budget=WORKFLOW_FILE_BUDGET_OPTIONAL,
        target_file_budget=WORKFLOW_FILE_BUDGET_REQUIRED,
        spec="## File Budget\n\n- `src/current.py`\n",
    )

    result = migrate_item_workflow_pin(
        test_db,
        item_id=ITEM_ID,
        target_version=int(target["version"]),
    )

    assert result["changed"] is True


def test_new_task_file_budget_requires_each_current_task_budget(test_db):
    _source, target = _publish_policy_pair(
        test_db,
        source_file_budget=WORKFLOW_FILE_BUDGET_OPTIONAL,
        target_file_budget=WORKFLOW_FILE_BUDGET_REQUIRED_PER_TASK,
    )
    insert_epic_task(test_db, epic_id=ITEM_ID, task_num=1)
    before = _pin(test_db)

    with pytest.raises(WorkflowRegistryError, match="File Budget policy"):
        migrate_item_workflow_pin(
            test_db,
            item_id=ITEM_ID,
            target_version=int(target["version"]),
        )

    assert _pin(test_db) == before


def test_new_task_file_budget_accepts_persisted_current_task_budget(test_db):
    _source, target = _publish_policy_pair(
        test_db,
        source_file_budget=WORKFLOW_FILE_BUDGET_OPTIONAL,
        target_file_budget=WORKFLOW_FILE_BUDGET_REQUIRED_PER_TASK,
    )
    insert_epic_task(test_db, epic_id=ITEM_ID, task_num=1)
    declare_task_files(test_db, ITEM_ID, 1, ["src/task.py"])
    test_db.commit()

    result = migrate_item_workflow_pin(
        test_db,
        item_id=ITEM_ID,
        target_version=int(target["version"]),
    )

    assert result["changed"] is True


def test_new_required_path_policy_rejects_missing_current_coverage(test_db) -> None:
    _source, target = _publish_policy_pair(
        test_db,
        source_path_claims=WORKFLOW_PATH_CLAIMS_OPTIONAL,
        target_path_claims=WORKFLOW_PATH_CLAIMS_REQUIRED,
    )
    before = _pin(test_db)

    with pytest.raises(
        WorkflowRegistryError,
        match="requires current coverage",
    ):
        migrate_item_workflow_pin(
            test_db,
            item_id=ITEM_ID,
            target_version=int(target["version"]),
        )

    assert _pin(test_db) == before


def test_new_required_path_policy_accepts_current_exception_coverage(test_db) -> None:
    _source, target = _publish_policy_pair(
        test_db,
        source_path_claims=WORKFLOW_PATH_CLAIMS_OPTIONAL,
        target_path_claims=WORKFLOW_PATH_CLAIMS_REQUIRED,
    )
    _seed_path_claim(test_db)

    result = migrate_item_workflow_pin(
        test_db,
        item_id=ITEM_ID,
        target_version=int(target["version"]),
    )

    assert result["changed"] is True


@pytest.mark.parametrize("with_item_claim", (False, True))
def test_per_task_path_policy_rejects_unrepresentable_parent_coverage(
    test_db,
    with_item_claim: bool,
) -> None:
    _source, target = _publish_policy_pair(
        test_db,
        target_path_claims=WORKFLOW_PATH_CLAIMS_REQUIRED_PER_TASK,
    )
    if with_item_claim:
        _seed_path_claim(test_db)

    with pytest.raises(
        WorkflowRegistryError,
        match="persisted task-to-claim binding",
    ):
        migrate_item_workflow_pin(
            test_db,
            item_id=ITEM_ID,
            target_version=int(target["version"]),
        )


def test_changed_worktree_policy_allows_exact_implementation_entry(test_db) -> None:
    _source, target = _publish_policy_pair(
        test_db,
        status="refined-idea",
        target_worktrees="worker_and_integration_lanes",
    )
    _seed_path_claim(test_db)

    result = migrate_item_workflow_pin(
        test_db,
        item_id=ITEM_ID,
        target_version=int(target["version"]),
    )

    assert result["changed"] is True
    assert result["after"]["status"] == "refined-idea"


def test_changed_worktree_policy_requires_lanes_after_implementation_entry(
    test_db,
) -> None:
    _source, target = _publish_policy_pair(
        test_db,
        target_worktrees="worker_and_integration_lanes",
    )
    _seed_path_claim(test_db)
    before = _pin(test_db)

    with pytest.raises(
        WorkflowRegistryError,
        match="missing=.*integration.*worker",
    ):
        migrate_item_workflow_pin(
            test_db,
            item_id=ITEM_ID,
            target_version=int(target["version"]),
        )

    assert _pin(test_db) == before


@pytest.mark.parametrize("status", ("failed",))
def test_changed_worktree_policy_fails_closed_for_wait_stages(
    test_db,
    status: str,
) -> None:
    _source, target = _publish_policy_pair(
        test_db,
        status=status,
        target_worktrees="worker_and_integration_lanes",
    )
    _seed_path_claim(test_db)

    with pytest.raises(
        WorkflowRegistryError,
        match="missing=.*integration.*worker",
    ):
        migrate_item_workflow_pin(
            test_db,
            item_id=ITEM_ID,
            target_version=int(target["version"]),
        )


@pytest.mark.parametrize("status", ("cancelled", "stopped"))
def test_changed_worktree_policy_exempts_engine_terminal_stages(
    test_db,
    status: str,
) -> None:
    _source, target = _publish_policy_pair(
        test_db,
        status=status,
        target_worktrees="worker_and_integration_lanes",
    )

    result = migrate_item_workflow_pin(
        test_db,
        item_id=ITEM_ID,
        target_version=int(target["version"]),
    )

    assert result["changed"] is True
    assert result["after"]["status"] == status
