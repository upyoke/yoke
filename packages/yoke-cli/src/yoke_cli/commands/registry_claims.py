"""Steering and coordination-claim entries for the aggregate ``yoke`` registry."""

from __future__ import annotations

from typing import Callable, Dict, List, Tuple

from yoke_cli.commands.adapters.claims_coordination_claim import (
    claims_coordination_claim_acquire,
    claims_coordination_claim_list,
    claims_coordination_claim_operator_release,
    claims_coordination_claim_release,
)
from yoke_cli.commands.adapters.claims_steering import (
    claims_steering_acquire,
    claims_steering_list,
    claims_steering_release,
)
from yoke_cli.commands.adapters.steering_report import steering_report_get
from yoke_cli.commands import flag_adapters as _adapters


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
    ("claims", "coordination-claim", "operator-release"): (
        "claims.coordination_claim.operator_release",
        claims_coordination_claim_operator_release,
    ),
    ("steering", "report", "get"): (
        "steering.report.get",
        steering_report_get,
    ),
}

CLAIMS_SUBCOMMAND_ALIAS_REGISTRY: Dict[Tuple[str, ...], Tuple[str, AdapterFn]] = {
    ("claims", "work", "list"): ("claims.work.holder_list", _adapters.claims_work_holder_list),
    ("claims", "work-claim", "acquire"): ("claims.work.acquire", _adapters.claims_work_acquire),
    ("claims", "work-claim", "release"): ("claims.work.release", _adapters.claims_work_release),
    ("claims", "work-claim", "list"): ("claims.work.holder_list", _adapters.claims_work_holder_list),
    ("claims", "work-claim", "get"): ("claims.work.holder_get", _adapters.claims_work_holder_get),
    ("coordination-claim", "list"): (
        "claims.coordination_claim.list",
        claims_coordination_claim_list,
    ),
    ("coordination-claim", "release"): (
        "claims.coordination_claim.operator_release",
        claims_coordination_claim_operator_release,
    ),
}


__all__ = [
    "CLAIMS_SUBCOMMAND_ALIAS_REGISTRY",
    "CLAIMS_SUBCOMMAND_REGISTRY",
]
