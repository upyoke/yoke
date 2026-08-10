"""DB-claim family entries for the aggregate registry."""

from __future__ import annotations

from typing import Callable, Dict, List, Tuple

from yoke_cli.commands.adapters.db_claim import (
    db_claim_amend,
    db_claim_prose_check,
)


AdapterFn = Callable[[List[str]], int]


DB_CLAIM_SUBCOMMAND_REGISTRY: Dict[Tuple[str, ...], Tuple[str, AdapterFn]] = {
    ("db-claim", "amend"): ("db_claim.amend", db_claim_amend),
    ("db-claim", "prose-check"): ("db_claim.prose_check", db_claim_prose_check),
}


__all__ = ["DB_CLAIM_SUBCOMMAND_REGISTRY"]
