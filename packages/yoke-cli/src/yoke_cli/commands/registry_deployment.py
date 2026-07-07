"""Deployment flow/run entries for the aggregate ``yoke`` registry."""

from __future__ import annotations

from typing import Callable, Dict, List, Tuple

from yoke_cli.commands import flag_adapters as _adapters


AdapterFn = Callable[[List[str]], int]


DEPLOYMENT_SUBCOMMAND_REGISTRY: Dict[Tuple[str, ...], Tuple[str, AdapterFn]] = {
    ("deployment-flows", "get"):
        ("deployment_flows.get", _adapters.deployment_flows_get),
    ("deployment-flows", "stages"):
        ("deployment_flows.stages", _adapters.deployment_flows_stages),
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
