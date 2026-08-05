"""Workflow-definition and item-pin CLI registry entries."""

from yoke_cli.commands.adapters.workflows_read import (
    workflows_current_set,
    workflows_definition_get,
    workflows_item_get,
    workflows_item_migrate,
    workflows_policy_defaults_publish,
    workflows_version_get,
    workflows_version_list,
)
from yoke_cli.commands.adapters.workflow_mechanics import (
    workflows_approval_defaults_publish,
    workflows_delivery_default_set,
    workflows_mechanics_get,
    workflows_testing_default_set,
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
    ("workflows", "version", "list"): (
        "workflows.version.list",
        workflows_version_list,
    ),
    ("workflows", "policy-defaults", "publish"): (
        "workflows.policy_defaults.publish",
        workflows_policy_defaults_publish,
    ),
    ("workflows", "item", "migrate"): (
        "workflows.item.migrate",
        workflows_item_migrate,
    ),
    ("workflows", "mechanics", "get"): (
        "workflows.mechanics.get",
        workflows_mechanics_get,
    ),
    ("workflows", "testing-default", "set"): (
        "workflows.testing_default.set",
        workflows_testing_default_set,
    ),
    ("workflows", "delivery-default", "set"): (
        "workflows.delivery_default.set",
        workflows_delivery_default_set,
    ),
    ("workflows", "approval-defaults", "publish"): (
        "workflows.approval_defaults.publish",
        workflows_approval_defaults_publish,
    ),
}
