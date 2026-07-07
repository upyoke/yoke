"""Readiness and path-claim gate entries for the aggregate registry."""

from __future__ import annotations

from typing import Callable, Dict, List, Tuple

from yoke_cli.commands import flag_adapters as _adapters


AdapterFn = Callable[[List[str]], int]


READINESS_SUBCOMMAND_REGISTRY: Dict[Tuple[str, ...], Tuple[str, AdapterFn]] = {
    ("readiness", "check"):
        ("readiness.check.run", _adapters.readiness_check),
    ("readiness", "prd-validate"):
        ("readiness.prd_validate.run", _adapters.readiness_prd_validate),
    ("readiness", "repair-stale-count"):
        ("readiness.repair_stale_count",
         _adapters.readiness_repair_stale_count),
    ("readiness", "repair-claim-coverage"):
        ("readiness.repair_claim_coverage",
         _adapters.readiness_repair_claim_coverage),
    ("claims", "path", "required-gate"):
        ("claims.path.required_gate", _adapters.claims_path_required_gate),
    ("claims", "path", "activation-run"):
        ("claims.path.activation_run", _adapters.claims_path_activation_run),
}


__all__ = ["READINESS_SUBCOMMAND_REGISTRY"]
