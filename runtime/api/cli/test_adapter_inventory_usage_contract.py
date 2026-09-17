"""Public CLI usage is the contract for structured adapter recipes."""

from __future__ import annotations

import re

from yoke_cli.commands.adapters.qa import (
    USAGE_BY_FUNCTION_ID as qa_write_usage,
)
from yoke_cli.commands.adapters.item_worktrees import (
    ITEM_WORKTREES_GET_USAGE,
    ITEM_WORKTREES_LIST_USAGE,
    ITEM_WORKTREES_PATH_RECORD_USAGE,
    ITEM_WORKTREES_RELEASE_USAGE,
)
from yoke_cli.commands.adapters.item_worktree_create import (
    ITEM_WORKTREES_CREATE_USAGE,
)
from yoke_cli.commands.adapters.qa_crud import QA_REQUIREMENT_ADD_USAGE
from yoke_cli.commands.adapters.qa_crud_batch import (
    QA_REQUIREMENT_ADD_BATCH_USAGE,
)
from yoke_cli.commands.adapters.qa_read import (
    QA_GATE_SUMMARY_USAGE,
    QA_REQUIREMENT_GET_USAGE,
    QA_REQUIREMENT_LIST_USAGE,
    QA_RUN_GET_USAGE,
    QA_RUN_LIST_USAGE,
)
from yoke_cli.commands.adapters.workflow_execution_instructions import (
    USAGE_BY_FUNCTION_ID as execution_instruction_usage,
)
from yoke_cli.commands.adapters.workflow_mechanics import (
    USAGE_BY_FUNCTION_ID as mechanics_usage,
)
from yoke_cli.commands.adapters.workflows_read import (
    WORKFLOWS_DEFINITION_GET_USAGE,
    WORKFLOWS_ITEM_GET_USAGE,
    WORKFLOWS_ITEM_MIGRATE_USAGE,
)
from yoke_cli.commands.adapters.workflows_item_posture import (
    WORKFLOWS_ITEM_POSTURE_AMEND_HELP,
    WORKFLOWS_ITEM_POSTURE_AMEND_USAGE,
)
from yoke_cli.commands.adapters.workflows_versions import (
    WORKFLOWS_CURRENT_SET_USAGE,
    WORKFLOWS_POLICY_DEFAULTS_PUBLISH_USAGE,
    WORKFLOWS_VERSION_GET_USAGE,
    WORKFLOWS_VERSION_LIST_USAGE,
)
from yoke_core.api.service_client_structured_api_adapter_inventory_qa import (
    QA_ADAPTERS,
)
from yoke_core.api.service_client_structured_api_adapter_inventory_items import (
    ITEMS_ADAPTERS,
)
from yoke_core.api.service_client_structured_api_adapter_inventory_workflows import (
    WORKFLOW_ADAPTERS,
)
from yoke_core.domain.qa_method_definitions import BUILTIN_QA_METHODS


def test_workflow_inventory_matches_public_cli_usage() -> None:
    expected = {
        "workflows.definition.get": WORKFLOWS_DEFINITION_GET_USAGE,
        "workflows.version.get": WORKFLOWS_VERSION_GET_USAGE,
        "workflows.version.list": WORKFLOWS_VERSION_LIST_USAGE,
        "workflows.item.get": WORKFLOWS_ITEM_GET_USAGE,
        "workflows.current.set": WORKFLOWS_CURRENT_SET_USAGE,
        "workflows.policy_defaults.publish": (WORKFLOWS_POLICY_DEFAULTS_PUBLISH_USAGE),
        "workflows.item.migrate": WORKFLOWS_ITEM_MIGRATE_USAGE,
        "workflows.item_posture.amend": WORKFLOWS_ITEM_POSTURE_AMEND_USAGE,
        **mechanics_usage,
        **execution_instruction_usage,
    }
    actual = {entry.function_id: entry.cli_invocation for entry in WORKFLOW_ADAPTERS}
    assert actual == expected


def test_converted_qa_inventory_matches_public_cli_usage() -> None:
    expected = {
        **qa_write_usage,
        "qa.requirement.list": QA_REQUIREMENT_LIST_USAGE,
        "qa.requirement.get": QA_REQUIREMENT_GET_USAGE,
        "qa.requirement.add": QA_REQUIREMENT_ADD_USAGE,
        "qa.requirement.add_batch": QA_REQUIREMENT_ADD_BATCH_USAGE,
        "qa.run.list": QA_RUN_LIST_USAGE,
        "qa.run.get": QA_RUN_GET_USAGE,
        "qa.gate_summary.run": QA_GATE_SUMMARY_USAGE,
    }
    actual = {
        entry.function_id: entry.cli_invocation
        for entry in QA_ADAPTERS
        if entry.function_id in expected
    }
    assert actual == expected


def test_item_worktree_inventory_matches_public_cli_usage() -> None:
    expected = {
        "item_worktrees.create": ITEM_WORKTREES_CREATE_USAGE,
        "item_worktrees.get": ITEM_WORKTREES_GET_USAGE,
        "item_worktrees.list": ITEM_WORKTREES_LIST_USAGE,
        "item_worktrees.path_record": ITEM_WORKTREES_PATH_RECORD_USAGE,
        "item_worktrees.release": ITEM_WORKTREES_RELEASE_USAGE,
    }
    actual = {
        entry.function_id: entry.cli_invocation
        for entry in ITEMS_ADAPTERS
        if entry.function_id in expected
    }
    assert actual == expected


def test_item_posture_amend_help_names_a_registered_verification_method() -> None:
    registered = {str(method["id"]) for method in BUILTIN_QA_METHODS}
    named = re.findall(
        r"--verification-method\s+(\S+)",
        WORKFLOWS_ITEM_POSTURE_AMEND_HELP,
    )
    assert named
    assert all(method_id in registered for method_id in named)
    assert "implementation_review" not in WORKFLOWS_ITEM_POSTURE_AMEND_HELP
