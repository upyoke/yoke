"""Steering and coordination-claim entries for the aggregate ``yoke`` registry."""

from __future__ import annotations

from typing import Callable, Dict, List, Tuple

from yoke_cli.commands.adapters.claims_coordination_claim import (
    claims_coordination_claim_list,
)
from yoke_cli.commands.adapters.claims_steering import (
    claims_steering_acquire,
    claims_steering_list,
    claims_steering_release,
)
from yoke_cli.commands.adapters.steering_backstop import steering_backstop_evaluate


AdapterFn = Callable[[List[str]], int]


CLAIMS_SUBCOMMAND_REGISTRY: Dict[Tuple[str, ...], Tuple[str, AdapterFn]] = {
    ("claims", "steering", "acquire"): (
        "claims.steering.acquire",
        claims_steering_acquire,
    ),
    ("claims", "steering", "release"): (
        "claims.steering.release",
        claims_steering_release,
    ),
    ("claims", "steering", "list"): (
        "claims.steering.list",
        claims_steering_list,
    ),
    ("claims", "coordination-claim", "list"): (
        "claims.coordination_claim.list",
        claims_coordination_claim_list,
    ),
    ("steering", "backstop", "evaluate"): (
        "steering.backstop.evaluate",
        steering_backstop_evaluate,
    ),
}

CLAIMS_SUBCOMMAND_ALIAS_REGISTRY: Dict[Tuple[str, ...], Tuple[str, AdapterFn]] = {
    ("coordination-claim", "list"): (
        "claims.coordination_claim.list",
        claims_coordination_claim_list,
    ),
}


__all__ = [
    "CLAIMS_SUBCOMMAND_ALIAS_REGISTRY",
    "CLAIMS_SUBCOMMAND_REGISTRY",
]
