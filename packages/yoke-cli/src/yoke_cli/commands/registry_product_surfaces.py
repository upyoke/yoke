"""Registry rows for workflow-aware product surfaces."""

from yoke_cli.commands.adapters import (
    harness_machine_report,
    inbox_decisions,
    item_worktree_create,
    item_worktrees,
    overview,
    qa_catalog,
    qa_catalog_defaults,
    qa_plan_edit,
    test_machine,
)
from yoke_cli.commands.registry_direct_workflows import (
    DIRECT_WORKFLOW_SUBCOMMAND_ALIAS_REGISTRY,
    DIRECT_WORKFLOW_SUBCOMMAND_REGISTRY,
)
from yoke_cli.commands.registry_item_pages import ITEM_PAGE_SUBCOMMAND_REGISTRY
from yoke_cli.commands.registry_project_structure import (
    PROJECT_STRUCTURE_SUBCOMMAND_REGISTRY,
)
from yoke_cli.commands.registry_strategy_surfaces import (
    STRATEGY_SURFACE_SUBCOMMAND_REGISTRY,
)
from yoke_cli.commands.registry_workflow_execution_instructions import (
    EXECUTION_INSTRUCTION_SUBCOMMAND_REGISTRY,
)


QA_CATALOG_SUBCOMMAND_REGISTRY = {
    ("qa", "method", "list"): ("qa.method.list", qa_catalog.qa_method_list),
    ("qa", "method", "get"): ("qa.method.get", qa_catalog.qa_method_get),
    ("qa", "project-method", "register"): (
        "qa.project_method.register",
        qa_catalog.qa_method_register,
    ),
    ("qa", "plan", "list"): ("qa.plan.list", qa_catalog.qa_plan_list),
    ("qa", "plan", "get"): ("qa.plan.get", qa_catalog.qa_plan_get),
    ("qa", "activity", "list"): (
        "qa.activity.list",
        qa_catalog.qa_activity_list,
    ),
    ("qa", "artifact", "read"): (
        "qa.artifact.read",
        qa_catalog.qa_artifact_read,
    ),
    ("qa", "plan", "create"): ("qa.plan.create", qa_catalog.qa_plan_create),
    ("qa", "plan", "edit"): ("qa.plan.edit", qa_plan_edit.qa_plan_edit),
    ("qa", "plan-cases", "replace"): (
        "qa.plan_cases.replace",
        qa_catalog.qa_plan_cases_replace,
    ),
    ("qa", "project-default", "set"): (
        "qa.project_default.set",
        qa_catalog_defaults.qa_plan_project_default_set,
    ),
    ("qa", "project-default", "unset"): (
        "qa.project_default.unset",
        qa_catalog_defaults.qa_plan_project_default_unset,
    ),
    ("qa", "item-plan", "attach"): (
        "qa.item_plan.attach",
        qa_catalog.qa_plan_item_attach,
    ),
    ("qa", "plan", "materialize"): (
        "qa.plan.materialize",
        qa_catalog.qa_plan_materialize_for_item,
    ),
    ("qa", "plan", "rematerialize"): (
        "qa.plan.rematerialize",
        qa_catalog.qa_plan_rematerialize,
    ),
}

TEST_MACHINE_SUBCOMMAND_REGISTRY = {
    ("test-machine", "get"): (
        "test_machine.get",
        test_machine.test_machine_get,
    ),
    ("test-machine", "settings-replace"): (
        "test_machine.settings_replace",
        test_machine.test_machine_settings_replace,
    ),
    ("test-machine", "verify"): (
        "test_machine.verify",
        test_machine.test_machine_verify,
    ),
}

INBOX_DECISION_SUBCOMMAND_REGISTRY = {
    ("inbox", "list"): ("inbox.list", inbox_decisions.inbox_list),
    ("decision-requests", "resolve"): (
        "decision_requests.resolve",
        inbox_decisions.decision_requests_resolve,
    ),
}

ITEM_WORKTREE_SUBCOMMAND_REGISTRY = {
    ("item-worktrees", "create"): (
        "item_worktrees.create",
        item_worktree_create.item_worktrees_create,
    ),
    ("item-worktrees", "get"): (
        "item_worktrees.get",
        item_worktrees.item_worktrees_get,
    ),
    ("item-worktrees", "list"): (
        "item_worktrees.list",
        item_worktrees.item_worktrees_list,
    ),
    ("item-worktrees", "path-record"): (
        "item_worktrees.path_record",
        item_worktrees.item_worktrees_path_record,
    ),
    ("item-worktrees", "release"): (
        "item_worktrees.release",
        item_worktrees.item_worktrees_release,
    ),
}

OVERVIEW_SUBCOMMAND_REGISTRY = {
    ("overview", "activation", "get"): (
        "overview.activation.get",
        overview.overview_activation_get,
    ),
    ("harness", "machine-report", "upsert"): (
        "harness.machine_report.upsert",
        harness_machine_report.harness_machine_report_upsert,
    ),
}

PRODUCT_SURFACE_SUBCOMMAND_REGISTRY = {
    **DIRECT_WORKFLOW_SUBCOMMAND_REGISTRY,
    **OVERVIEW_SUBCOMMAND_REGISTRY,
    **EXECUTION_INSTRUCTION_SUBCOMMAND_REGISTRY,
    **INBOX_DECISION_SUBCOMMAND_REGISTRY,
    **ITEM_PAGE_SUBCOMMAND_REGISTRY,
    **ITEM_WORKTREE_SUBCOMMAND_REGISTRY,
    **PROJECT_STRUCTURE_SUBCOMMAND_REGISTRY,
    **QA_CATALOG_SUBCOMMAND_REGISTRY,
    **STRATEGY_SURFACE_SUBCOMMAND_REGISTRY,
    **TEST_MACHINE_SUBCOMMAND_REGISTRY,
}
PRODUCT_SURFACE_SUBCOMMAND_ALIAS_REGISTRY = {
    **DIRECT_WORKFLOW_SUBCOMMAND_ALIAS_REGISTRY,
}


__all__ = [
    "INBOX_DECISION_SUBCOMMAND_REGISTRY",
    "PRODUCT_SURFACE_SUBCOMMAND_ALIAS_REGISTRY",
    "PRODUCT_SURFACE_SUBCOMMAND_REGISTRY",
]
