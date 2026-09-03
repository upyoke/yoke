"""Steering and coordination-claim entries for the aggregate ``yoke`` registry."""

from __future__ import annotations

from typing import Callable, Dict, List, Tuple

from yoke_cli.commands.adapters.claims_coordination_claim import (
    claims_coordination_claim_acquire,
    claims_coordination_claim_list,
    claims_coordination_claim_release,
)
from yoke_cli.commands.adapters.claims_steering import (
    claims_steering_acquire,
    claims_steering_list,
    claims_steering_release,
)
from yoke_cli.commands.adapters.steering_report import steering_report_get


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
    ("claims", "coordination-claim", "acquire"): (
        "claims.coordination_claim.acquire",
        claims_coordination_claim_acquire,
    ),
    ("claims", "coordination-claim", "list"): (
        "claims.coordination_claim.list",
        claims_coordination_claim_list,
    ),
    ("claims", "coordination-claim", "release"): (
        "claims.coordination_claim.release",
        claims_coordination_claim_release,
    ),
    ("steering", "report", "get"): (
        "steering.report.get",
        steering_report_get,
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
