"""Workflow-definition and item-pin CLI registry entries."""

from yoke_cli.commands.adapters.workflows_read import (
    workflows_current_set,
    workflows_definition_get,
    workflows_item_get,
    workflows_item_migrate,
    workflows_policy_defaults_publish,
    workflows_version_get,
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
    ("workflows", "version", "get"): (
        "workflows.version.get",
        workflows_version_get,
    ),
    ("workflows", "policy-defaults", "publish"): (
        "workflows.policy_defaults.publish",
        workflows_policy_defaults_publish,
    ),
    ("workflows", "item", "migrate"): (
        "workflows.item.migrate",
        workflows_item_migrate,
    ),
}
