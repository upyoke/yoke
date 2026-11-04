"""DB-claim family entries for the aggregate registry."""

from __future__ import annotations

from typing import Callable, Dict, List, Tuple

from yoke_cli.commands.adapters.db_claim import (
    db_claim_amend,
)


AdapterFn = Callable[[List[str]], int]


DB_CLAIM_SUBCOMMAND_REGISTRY: Dict[Tuple[str, ...], Tuple[str, AdapterFn]] = {
    ("db-claim", "amend"): ("db_claim.amend", db_claim_amend),
}


__all__ = ["DB_CLAIM_SUBCOMMAND_REGISTRY"]
