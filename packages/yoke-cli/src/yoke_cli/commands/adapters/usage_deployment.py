"""Function-id to usage-string map for the deployment adapters.

Split out of the aggregate usage map so the deployment family's imports and
entries live together and the aggregate stays inside the authored-file limit.
"""

from __future__ import annotations

from yoke_cli.commands.adapters.deployment import (
    DEPLOYMENT_FLOWS_GET_USAGE,
    DEPLOYMENT_FLOWS_SET_STATUS_USAGE,
    DEPLOYMENT_FLOWS_STAGES_USAGE,
    DEPLOYMENT_RUNS_APPROVE_USAGE,
    DEPLOYMENT_RUNS_GET_USAGE,
    DEPLOYMENT_RUNS_LIST_USAGE,
    DEPLOYMENT_RUNS_RESOLVE_TARGET_ENV_USAGE,
    DEPLOYMENT_RUNS_UPDATE_USAGE,
)
from yoke_cli.commands.adapters.deployment_composed import (
    DEPLOYMENT_FLOWS_DESCRIBE_USAGE,
)
from yoke_cli.commands.adapters.deployment_run_create import (
    DEPLOYMENT_RUNS_CREATE_USAGE,
)
from yoke_cli.commands.adapters.deployment_run_terminalize import (
    DEPLOYMENT_RUNS_TERMINALIZE_USAGE,
)
from yoke_cli.commands.adapters.deployment_inspection import (
    DEPLOYMENT_FLOWS_LIST_USAGE,
    DEPLOYMENT_RUNS_FIND_BY_ITEM_USAGE,
    DEPLOYMENT_RUNS_STAGES_USAGE,
)


DEPLOYMENT_USAGE = {
    "deployment_flows.describe": DEPLOYMENT_FLOWS_DESCRIBE_USAGE,
    "deployment_flows.get": DEPLOYMENT_FLOWS_GET_USAGE,
    "deployment_flows.list": DEPLOYMENT_FLOWS_LIST_USAGE,
    "deployment_flows.set_status": DEPLOYMENT_FLOWS_SET_STATUS_USAGE,
    "deployment_flows.stages": DEPLOYMENT_FLOWS_STAGES_USAGE,
    "deployment_runs.create": DEPLOYMENT_RUNS_CREATE_USAGE,
    "deployment_runs.approve": DEPLOYMENT_RUNS_APPROVE_USAGE,
    "deployment_runs.get": DEPLOYMENT_RUNS_GET_USAGE,
    "deployment_runs.find_by_item": DEPLOYMENT_RUNS_FIND_BY_ITEM_USAGE,
    "deployment_runs.list": DEPLOYMENT_RUNS_LIST_USAGE,
    "deployment_runs.stages": DEPLOYMENT_RUNS_STAGES_USAGE,
    "deployment_runs.update": DEPLOYMENT_RUNS_UPDATE_USAGE,
    "deployment_runs.terminalize": DEPLOYMENT_RUNS_TERMINALIZE_USAGE,
    "deployment_runs.resolve_target_env": (
        DEPLOYMENT_RUNS_RESOLVE_TARGET_ENV_USAGE
    ),
}


__all__ = ["DEPLOYMENT_USAGE"]
