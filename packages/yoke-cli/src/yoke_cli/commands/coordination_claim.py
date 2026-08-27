"""Human-only local authority adapter for stranded coordination claims."""

from __future__ import annotations

import importlib
import sys
from typing import Callable, Dict, List, Tuple

from yoke_cli.commands.migration_rehearse import remote_without_admin_authority
from yoke_contracts.coordination_claim_recovery import OPERATOR_RELEASE_USAGE


AdapterFn = Callable[[List[str]], int]


def coordination_claim_release(args: List[str]) -> int:
    """Delegate recovery to the installed runtime's audited operator surface."""
    if any(arg in {"-h", "--help"} for arg in args):
        print(OPERATOR_RELEASE_USAGE)
        return 0
    if remote_without_admin_authority():
        print(
            "yoke coordination-claim release refused: select the matching "
            "local-Postgres or db-admin connection; this human-only recovery "
            "operation is not relayed over HTTPS.",
            file=sys.stderr,
        )
        return 1
    module = importlib.import_module("yoke_core.api.service_client_coordination_claims")
    return int(module.cmd_coordination_claim_release(args))


TOOL_SHAPED_SUBCOMMANDS: Dict[Tuple[str, ...], AdapterFn] = {
    ("coordination-claim", "release"): coordination_claim_release,
}
TOOL_SHAPED_USAGE: Dict[str, str] = {
    "yoke coordination-claim release": OPERATOR_RELEASE_USAGE,
}


__all__ = [
    "OPERATOR_RELEASE_USAGE",
    "TOOL_SHAPED_SUBCOMMANDS",
    "TOOL_SHAPED_USAGE",
    "coordination_claim_release",
]
