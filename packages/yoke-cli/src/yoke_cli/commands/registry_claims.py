"""Coordination-lease list entries for the aggregate ``yoke`` registry."""

from __future__ import annotations

from typing import Callable, Dict, List, Tuple

from yoke_cli.commands.adapters.claims_coordination_lease import (
    claims_coordination_lease_list,
)
from yoke_cli.commands.adapters.claims_steering_scope import (
    claims_steering_scope_acquire,
    claims_steering_scope_list,
    claims_steering_scope_release,
)


AdapterFn = Callable[[List[str]], int]


CLAIMS_SUBCOMMAND_REGISTRY: Dict[Tuple[str, ...], Tuple[str, AdapterFn]] = {
    ("claims", "steering-scope", "acquire"): (
        "claims.steering_scope.acquire",
        claims_steering_scope_acquire,
    ),
    ("claims", "steering-scope", "release"): (
        "claims.steering_scope.release",
        claims_steering_scope_release,
    ),
    ("claims", "steering-scope", "list"): (
        "claims.steering_scope.list",
        claims_steering_scope_list,
    ),
    ("claims", "coordination-lease", "list"): (
        "claims.coordination_lease.list",
        claims_coordination_lease_list,
    ),
}

CLAIMS_SUBCOMMAND_ALIAS_REGISTRY: Dict[Tuple[str, ...], Tuple[str, AdapterFn]] = {
    ("coordination-lease", "list"): (
        "claims.coordination_lease.list",
        claims_coordination_lease_list,
    ),
}


__all__ = [
    "CLAIMS_SUBCOMMAND_ALIAS_REGISTRY",
    "CLAIMS_SUBCOMMAND_REGISTRY",
]
