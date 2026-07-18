"""Deployment flow/run entries for the aggregate ``yoke`` registry."""

from __future__ import annotations

from typing import Callable, Dict, List, Tuple

from yoke_cli.commands import flag_adapters as _adapters
from yoke_cli.commands.adapters.deployment_flow_reconcile import (
    deployment_flows_reconcile_project,
)


AdapterFn = Callable[[List[str]], int]


DEPLOYMENT_SUBCOMMAND_REGISTRY: Dict[Tuple[str, ...], Tuple[str, AdapterFn]] = {
    ("deployment-flows", "get"):
        ("deployment_flows.get", _adapters.deployment_flows_get),
    ("deployment-flows", "reconcile-project"):
        (
            "deployment_flows.reconcile_project",
            deployment_flows_reconcile_project,
        ),
    ("deployment-flows", "stages"):
        ("deployment_flows.stages", _adapters.deployment_flows_stages),
    ("deployment-flows", "update-stages"):
        ("deployment_flows.update_stages",
         _adapters.deployment_flows_update_stages),
    ("deployment-flows", "set-status"):
        ("deployment_flows.set_status", _adapters.deployment_flows_set_status),
    ("deployment-runs", "create"):
        ("deployment_runs.create", _adapters.deployment_runs_create),
    ("deployment-runs", "start-for-item"):
        ("deployment_runs.start_for_item",
         _adapters.deployment_runs_start_for_item),
    ("deployment-runs", "approve"):
        ("deployment_runs.approve", _adapters.deployment_runs_approve),
    ("deployment-runs", "get"):
        ("deployment_runs.get", _adapters.deployment_runs_get),
    ("deployment-runs", "list"):
        ("deployment_runs.list", _adapters.deployment_runs_list),
    ("deployment-runs", "update"):
        ("deployment_runs.update", _adapters.deployment_runs_update),
    ("deployment-runs", "resolve-target-env"):
        ("deployment_runs.resolve_target_env",
         _adapters.deployment_runs_resolve_target_env),
}


__all__ = ["DEPLOYMENT_SUBCOMMAND_REGISTRY"]
