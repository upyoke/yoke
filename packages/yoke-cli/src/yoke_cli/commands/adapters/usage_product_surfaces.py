"""Usage rows for workflow-aware product surfaces."""

from yoke_cli.commands.adapters import (
    direct_workflow_usage,
    item_pages,
    item_worktree_create,
    item_worktrees,
    projects_capabilities_read,
    qa_catalog,
    qa_plan_edit,
    strategy_surfaces,
    test_machine,
    workflow_mechanics,
    workflows_read,
)


USAGE_BY_FUNCTION_ID = {
    "workflows.current.set": workflows_read.WORKFLOWS_CURRENT_SET_USAGE,
    "workflows.definition.get": workflows_read.WORKFLOWS_DEFINITION_GET_USAGE,
    "workflows.item.get": workflows_read.WORKFLOWS_ITEM_GET_USAGE,
    "workflows.item.migrate": workflows_read.WORKFLOWS_ITEM_MIGRATE_USAGE,
    "workflows.policy_defaults.publish": (
        workflows_read.WORKFLOWS_POLICY_DEFAULTS_PUBLISH_USAGE
    ),
    "workflows.version.get": workflows_read.WORKFLOWS_VERSION_GET_USAGE,
    "item_worktrees.create": (item_worktree_create.ITEM_WORKTREES_CREATE_USAGE),
    "item_worktrees.get": item_worktrees.ITEM_WORKTREES_GET_USAGE,
    "item_worktrees.list": item_worktrees.ITEM_WORKTREES_LIST_USAGE,
    "item_worktrees.path_record": (
        item_worktrees.ITEM_WORKTREES_PATH_RECORD_USAGE
    ),
    "item_worktrees.release": item_worktrees.ITEM_WORKTREES_RELEASE_USAGE,
    "projects.capabilities.list": (
        projects_capabilities_read.PROJECTS_CAPABILITIES_LIST_USAGE
    ),
    **direct_workflow_usage.USAGE_BY_FUNCTION_ID,
    **item_pages.USAGE_BY_FUNCTION_ID,
    **qa_catalog.USAGE_BY_FUNCTION_ID,
    **qa_plan_edit.USAGE_BY_FUNCTION_ID,
    **strategy_surfaces.USAGE_BY_FUNCTION_ID,
    **test_machine.USAGE_BY_FUNCTION_ID,
    **workflow_mechanics.USAGE_BY_FUNCTION_ID,
}


__all__ = ["USAGE_BY_FUNCTION_ID"]
