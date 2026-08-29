"""Item coordination-flag entries for the aggregate ``yoke`` registry."""

from __future__ import annotations

from typing import Callable, Dict, List, Tuple

from yoke_cli.commands.adapters.items_cancel import items_cancel
from yoke_cli.commands.adapters.items_flags import (
    items_block,
    items_freeze,
    items_thaw,
    items_unblock,
)


AdapterFn = Callable[[List[str]], int]


ITEMS_FLAGS_SUBCOMMAND_REGISTRY: Dict[Tuple[str, ...], Tuple[str, AdapterFn]] = {
    ("items", "freeze"): ("items.freeze.run", items_freeze),
    ("items", "thaw"): ("items.thaw.run", items_thaw),
    ("items", "block"): ("items.block.run", items_block),
    ("items", "unblock"): ("items.unblock.run", items_unblock),
    ("items", "cancel"): ("items.cancel.run", items_cancel),
}


__all__ = ["ITEMS_FLAGS_SUBCOMMAND_REGISTRY"]
