"""Shepherd dependency entries for the aggregate ``yoke`` registry."""

from __future__ import annotations

from typing import Callable, Dict, List, Tuple

from yoke_cli.commands import flag_adapters as _adapters


AdapterFn = Callable[[List[str]], int]


SHEPHERD_DEPENDENCY_SUBCOMMAND_REGISTRY: Dict[
    Tuple[str, ...], Tuple[str, AdapterFn]
] = {
    ("shepherd", "dependency-list"):
        ("shepherd.dependency_list.run", _adapters.shepherd_dependency_list),
    ("shepherd", "dependency-add"):
        ("shepherd.dependency_add.run", _adapters.shepherd_dependency_add),
    ("shepherd", "dependency-update"):
        ("shepherd.dependency_update.run", _adapters.shepherd_dependency_update),
    ("shepherd", "dependency-remove"):
        ("shepherd.dependency_remove.run", _adapters.shepherd_dependency_remove),
    ("shepherd", "verdict"):
        ("shepherd.verdict.run", _adapters.shepherd_verdict),
    ("shepherd", "caveat-disposition"):
        ("shepherd.caveat_disposition.run",
         _adapters.shepherd_caveat_disposition),
}


__all__ = ["SHEPHERD_DEPENDENCY_SUBCOMMAND_REGISTRY"]
