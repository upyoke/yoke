# ruff: noqa: F401, E402
"""Shared setup for tests in this directory."""

from __future__ import annotations

from copy import deepcopy

import pytest

from runtime.api.domain.workflow_item_migration_compatibility_test_support import (
    ITEM_ID,
    _pin,
    _seed_path_claim,
)

from runtime.api.fixtures.backlog import insert_item

from runtime.api.fixtures.backlog_inserts import insert_epic_task

from runtime.api.task_files_touched_test_support import declare_task_files

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
