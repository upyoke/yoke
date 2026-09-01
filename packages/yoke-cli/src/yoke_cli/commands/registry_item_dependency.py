"""Item-dependency entries for the aggregate ``yoke`` registry."""

from __future__ import annotations

from typing import Callable, Dict, List, Tuple

from yoke_cli.commands import flag_adapters as _adapters


AdapterFn = Callable[[List[str]], int]


ITEM_DEPENDENCY_SUBCOMMAND_REGISTRY: Dict[
    Tuple[str, ...], Tuple[str, AdapterFn]
] = {
    ("items", "dependency", "list"):
        ("items.dependency.list", _adapters.items_dependency_list),
    ("items", "dependency", "add"):
        ("items.dependency.add", _adapters.items_dependency_add),
    ("items", "dependency", "update"):
        ("items.dependency.update", _adapters.items_dependency_update),
    ("items", "dependency", "remove"):
        ("items.dependency.remove", _adapters.items_dependency_remove),
}


__all__ = ["ITEM_DEPENDENCY_SUBCOMMAND_REGISTRY"]
