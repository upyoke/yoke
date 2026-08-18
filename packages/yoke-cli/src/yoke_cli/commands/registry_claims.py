"""Coordination-lease list entries for the aggregate ``yoke`` registry."""

from __future__ import annotations

from typing import Callable, Dict, List, Tuple

from yoke_cli.commands.adapters.claims_coordination_lease import (
    claims_coordination_lease_list,
)


AdapterFn = Callable[[List[str]], int]


CLAIMS_SUBCOMMAND_REGISTRY: Dict[Tuple[str, ...], Tuple[str, AdapterFn]] = {
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
