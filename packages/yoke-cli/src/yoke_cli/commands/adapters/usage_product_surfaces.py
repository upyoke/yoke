"""Usage rows for workflow-aware product surfaces."""

from yoke_cli.commands.adapters import (
    direct_workflow_usage,
    item_pages,
    qa_catalog,
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
    **direct_workflow_usage.USAGE_BY_FUNCTION_ID,
    **item_pages.USAGE_BY_FUNCTION_ID,
    **qa_catalog.USAGE_BY_FUNCTION_ID,
    **strategy_surfaces.USAGE_BY_FUNCTION_ID,
    **test_machine.USAGE_BY_FUNCTION_ID,
    **workflow_mechanics.USAGE_BY_FUNCTION_ID,
}


__all__ = ["USAGE_BY_FUNCTION_ID"]
