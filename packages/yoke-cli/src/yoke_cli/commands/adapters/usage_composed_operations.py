"""Usage map for composed operations and extension command families."""

from yoke_cli.commands.adapters.deployment_composed import (
    DEPLOYMENT_FLOWS_UPDATE_STAGES_USAGE,
    DEPLOYMENT_RUNS_START_FOR_ITEM_USAGE,
)
from yoke_cli.commands.adapters.deployment_flow_reconcile import (
    USAGE as DEPLOYMENT_FLOWS_RECONCILE_PROJECT_USAGE,
)
from yoke_cli.commands.adapters.ephemeral_env import EPHEMERAL_ENV_CREATE_USAGE
from yoke_cli.commands.adapters.ouroboros_writes import OUROBOROS_WRAPUP_SAVE_USAGE
from yoke_cli.commands.adapters.project_artifacts import (
    PROJECT_ARTIFACTS_REFRESH_USAGE,
)
from yoke_cli.commands.adapters.projects_infrastructure import (
    PROJECTS_INFRASTRUCTURE_LIST_USAGE,
)
from yoke_cli.commands.adapters.usage_github_actions import (
    USAGE_BY_FUNCTION_ID as GITHUB_ACTIONS_USAGE_BY_ID,
)


USAGE_BY_FUNCTION_ID = {
    **GITHUB_ACTIONS_USAGE_BY_ID,
    "deployment_flows.reconcile_project": (
        DEPLOYMENT_FLOWS_RECONCILE_PROJECT_USAGE
    ),
    "deployment_flows.update_stages": DEPLOYMENT_FLOWS_UPDATE_STAGES_USAGE,
    "deployment_runs.start_for_item": DEPLOYMENT_RUNS_START_FOR_ITEM_USAGE,
    "ephemeral_env.create": EPHEMERAL_ENV_CREATE_USAGE,
    "ouroboros.wrapup.save": OUROBOROS_WRAPUP_SAVE_USAGE,
    "project.artifacts.refresh": PROJECT_ARTIFACTS_REFRESH_USAGE,
    "projects.infrastructure.list": PROJECTS_INFRASTRUCTURE_LIST_USAGE,
}


__all__ = ["USAGE_BY_FUNCTION_ID"]
