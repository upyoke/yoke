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
from yoke_cli.commands.adapters.workflows_canon import (
    workflows_canon_follow_set,
    workflows_canon_status_list,
    workflows_canon_update_apply,
    workflows_canon_update_apply_all,
    workflows_canon_update_preview,
)
from yoke_cli.commands.adapters.workflows_item_posture import (
    workflows_item_posture_amend,
)
from yoke_cli.commands.adapters.workflow_mechanics import (
    workflows_approval_defaults_publish,
    workflows_delivery_default_set,
    workflows_mechanics_get,
    workflows_testing_default_set,
)

from yoke_cli.commands.adapters.workflows_publication import workflows_version_publish

WORKFLOW_SUBCOMMAND_REGISTRY = {
    ("workflows", "version", "publish"): (
        "workflows.version.publish",
        workflows_version_publish,
    ),
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
    ("workflows", "item-posture", "amend"): (
        "workflows.item_posture.amend",
        workflows_item_posture_amend,
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
    ("workflows", "canon-status", "list"): (
        "workflows.canon_status.list",
        workflows_canon_status_list,
    ),
    ("workflows", "canon-update", "preview"): (
        "workflows.canon_update.preview",
        workflows_canon_update_preview,
    ),
    ("workflows", "canon-update", "apply"): (
        "workflows.canon_update.apply",
        workflows_canon_update_apply,
    ),
    ("workflows", "canon-update", "apply-all"): (
        "workflows.canon_update.apply_all",
        workflows_canon_update_apply_all,
    ),
    ("workflows", "canon-follow", "set"): (
        "workflows.canon_follow.set",
        workflows_canon_follow_set,
    ),
    ("workflows", "approval-defaults", "publish"): (
        "workflows.approval_defaults.publish",
        workflows_approval_defaults_publish,
    ),
}
