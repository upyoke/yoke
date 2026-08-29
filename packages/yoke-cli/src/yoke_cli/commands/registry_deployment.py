"""Deployment flow/run entries for the aggregate ``yoke`` registry."""

from __future__ import annotations

from typing import Callable, Dict, List, Tuple

from yoke_cli.commands import flag_adapters as _adapters
from yoke_cli.commands.adapters.deployment_flow_create import (
    deployment_flows_create,
)
from yoke_cli.commands.adapters import deployment_inspection as _inspection
from yoke_cli.commands.adapters.deployment_run_projection import (
    deployment_runs_project_snapshot,
)
from yoke_cli.commands.adapters.deployment_run_terminalize import (
    deployment_runs_terminalize,
)


AdapterFn = Callable[[List[str]], int]


DEPLOYMENT_SUBCOMMAND_REGISTRY: Dict[Tuple[str, ...], Tuple[str, AdapterFn]] = {
    ("deployment-flows", "list"):
        ("deployment_flows.list", _inspection.deployment_flows_list),
    ("deployment-flows", "get"):
        ("deployment_flows.get", _adapters.deployment_flows_get),
    ("deployment-flows", "create"):
        ("deployment_flows.create", deployment_flows_create),
    ("deployment-flows", "stages"):
        ("deployment_flows.stages", _adapters.deployment_flows_stages),
    ("deployment-flows", "update-stages"):
        ("deployment_flows.update_stages",
         _adapters.deployment_flows_update_stages),
    ("deployment-flows", "describe"):
        ("deployment_flows.describe",
         _adapters.deployment_flows_describe),
    ("deployment-flows", "set-status"):
        ("deployment_flows.set_status", _adapters.deployment_flows_set_status),
    ("deployment-runs", "create"):
        ("deployment_runs.create", _adapters.deployment_runs_create),
    ("deployment-runs", "project-snapshot"):
        ("deployment_runs.project_snapshot", deployment_runs_project_snapshot),
    ("deployment-runs", "start-for-item"):
        ("deployment_runs.start_for_item",
         _adapters.deployment_runs_start_for_item),
    ("deployment-runs", "approve"):
        ("deployment_runs.approve", _adapters.deployment_runs_approve),
    ("deployment-runs", "get"):
        ("deployment_runs.get", _adapters.deployment_runs_get),
    ("deployment-runs", "list"):
        ("deployment_runs.list", _adapters.deployment_runs_list),
    ("deployment-runs", "find-by-item"):
        (
            "deployment_runs.find_by_item",
            _inspection.deployment_runs_find_by_item,
        ),
    ("deployment-runs", "failure-trace"):
        (
            "deployment_runs.failure_trace",
            _inspection.deployment_runs_failure_trace,
        ),
    ("deployment-runs", "stages"):
        ("deployment_runs.stages", _inspection.deployment_runs_stages),
    ("deployment-runs", "update"):
        ("deployment_runs.update", _adapters.deployment_runs_update),
    ("deployment-runs", "terminalize"):
        ("deployment_runs.terminalize", deployment_runs_terminalize),
    ("deployment-runs", "resolve-target"):
        ("deployment_runs.resolve_target",
         _adapters.deployment_runs_resolve_target),
}


__all__ = ["DEPLOYMENT_SUBCOMMAND_REGISTRY"]
