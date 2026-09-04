"""Usage map for composed operations and extension command families."""

from yoke_cli.commands.adapters.deployment_composed import (
    DEPLOYMENT_FLOWS_UPDATE_STAGES_USAGE,
    DEPLOYMENT_RUNS_START_FOR_ITEM_USAGE,
)
from yoke_cli.commands.adapters.deployment_flow_create import (
    USAGE as DEPLOYMENT_FLOWS_CREATE_USAGE,
)
from yoke_cli.commands.adapters.deployment_run_projection import (
    USAGE as DEPLOYMENT_RUNS_PROJECT_SNAPSHOT_USAGE,
)
from yoke_cli.commands.adapters.ephemeral_env import EPHEMERAL_ENV_CREATE_USAGE
from yoke_cli.commands.adapters.projects_infrastructure import (
    PROJECTS_INFRASTRUCTURE_LIST_USAGE,
)
from yoke_cli.commands.adapters.github_merge_queue import (
    GITHUB_MERGE_QUEUE_APPLY_USAGE,
    GITHUB_MERGE_QUEUE_READINESS_USAGE,
)
from yoke_cli.commands.adapters.usage_github_actions import (
    USAGE_BY_FUNCTION_ID as GITHUB_ACTIONS_USAGE_BY_ID,
)


USAGE_BY_FUNCTION_ID = {
    **GITHUB_ACTIONS_USAGE_BY_ID,
    "github.merge_queue.apply": GITHUB_MERGE_QUEUE_APPLY_USAGE,
    "github.merge_queue.readiness": GITHUB_MERGE_QUEUE_READINESS_USAGE,
    "deployment_flows.create": DEPLOYMENT_FLOWS_CREATE_USAGE,
    "deployment_flows.update_stages": DEPLOYMENT_FLOWS_UPDATE_STAGES_USAGE,
    "deployment_runs.start_for_item": DEPLOYMENT_RUNS_START_FOR_ITEM_USAGE,
    "deployment_runs.project_snapshot": DEPLOYMENT_RUNS_PROJECT_SNAPSHOT_USAGE,
    "ephemeral_env.create": EPHEMERAL_ENV_CREATE_USAGE,
    "projects.infrastructure.list": PROJECTS_INFRASTRUCTURE_LIST_USAGE,
}


__all__ = ["USAGE_BY_FUNCTION_ID"]
