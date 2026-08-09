"""Path-claim and worktree obligations introduced by workflow migration."""

from __future__ import annotations

from copy import deepcopy

import pytest

from runtime.api.domain.test_workflow_item_migration_compatibility import (
    ITEM_ID,
    _pin,
    _seed_path_claim,
)
from runtime.api.fixtures.backlog import insert_item
from runtime.api.fixtures.backlog_inserts import insert_epic_task
from yoke_core.domain import epic
from yoke_core.domain.builtin_workflow_definitions import (
    builtin_workflow_definition,
)
from yoke_core.domain.workflow_definition_builders import (
    with_generated_epic_tasks,
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
from yoke_core.domain.workflow_registry import publish_workflow_version


def _publish_policy_pair(
    test_db,
    *,
    status: str = "implementing",
    source_path_claims: str = WORKFLOW_PATH_CLAIMS_REQUIRED,
    target_path_claims: str | None = None,
    source_file_budget: str = WORKFLOW_FILE_BUDGET_REQUIRED,
    target_file_budget: str | None = None,
    spec: str = "",
    source_worktrees: str = "single_implementation_lane",
    target_worktrees: str | None = None,
) -> tuple[dict, dict]:
    source_definition = deepcopy(builtin_workflow_definition("issue")["definition"])
    source_definition["stages"][0]["label"] = "Policy migration candidate"
    source_definition["policies"]["path_claims"] = source_path_claims
    source_definition["policies"]["file_budget"] = source_file_budget
    source_definition["policies"]["worktrees"] = source_worktrees
    source = publish_workflow_version(
        test_db,
        workflow_id="issue",
        definition=source_definition,
    )
    insert_item(
        test_db,
        id=ITEM_ID,
        workflow_id="issue",
        status=status,
        spec=spec,
    )

    target_definition = deepcopy(source_definition)
    target_definition["stages"][0]["label"] = "Policy migration target"
    if target_path_claims is not None:
        target_definition["policies"]["path_claims"] = target_path_claims
    if target_file_budget is not None:
        target_definition["policies"]["file_budget"] = target_file_budget
    if (
        target_definition["policies"]["file_budget"]
        == WORKFLOW_FILE_BUDGET_REQUIRED_PER_TASK
        or target_definition["policies"]["path_claims"]
        == WORKFLOW_PATH_CLAIMS_REQUIRED_PER_TASK
    ):
        with_generated_epic_tasks(target_definition)
    if target_worktrees is not None:
        target_definition["policies"]["worktrees"] = target_worktrees
    target = publish_workflow_version(
        test_db,
        workflow_id="issue",
        definition=target_definition,
    )
    return source, target


def test_new_required_file_budget_rejects_missing_current_coverage(test_db):
    _source, target = _publish_policy_pair(
        test_db,
        source_file_budget=WORKFLOW_FILE_BUDGET_OPTIONAL,
        target_file_budget=WORKFLOW_FILE_BUDGET_REQUIRED,
    )
    before = _pin(test_db)

    with pytest.raises(WorkflowRegistryError, match="File Budget policy"):
        migrate_item_workflow_pin(
            test_db, item_id=ITEM_ID, target_version=int(target["version"]),
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
        test_db, item_id=ITEM_ID, target_version=int(target["version"]),
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
            test_db, item_id=ITEM_ID, target_version=int(target["version"]),
        )

    assert _pin(test_db) == before


def test_new_task_file_budget_accepts_persisted_current_task_budget(test_db):
    _source, target = _publish_policy_pair(
        test_db,
        source_file_budget=WORKFLOW_FILE_BUDGET_OPTIONAL,
        target_file_budget=WORKFLOW_FILE_BUDGET_REQUIRED_PER_TASK,
    )
    insert_epic_task(test_db, epic_id=ITEM_ID, task_num=1)
    epic.file_add(test_db, str(ITEM_ID), 1, "src/task.py", "modify")

    result = migrate_item_workflow_pin(
        test_db, item_id=ITEM_ID, target_version=int(target["version"]),
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


@pytest.mark.parametrize("status", ("blocked", "failed"))
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
