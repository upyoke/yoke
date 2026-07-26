"""Workflow-definition and item-pin CLI registry entries."""

from yoke_cli.commands.adapters.workflows_read import (
    workflows_current_set,
    workflows_definition_get,
    workflows_item_get,
    workflows_item_migrate,
)

WORKFLOW_SUBCOMMAND_REGISTRY = {
    ("workflows", "definition", "get"): (
        "workflows.definition.get",
        workflows_definition_get,
    ),
    ("workflows", "item", "get"): (
        "workflows.item.get",
        workflows_item_get,
    ),
    ("workflows", "current", "set"): (
        "workflows.current.set",
        workflows_current_set,
    ),
    ("workflows", "item", "migrate"): (
        "workflows.item.migrate",
        workflows_item_migrate,
    ),
}
