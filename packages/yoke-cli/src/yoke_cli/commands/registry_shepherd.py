"""Shepherd Architect/Boss entries for the aggregate ``yoke`` registry."""

from __future__ import annotations

from typing import Callable, Dict, List, Tuple

from yoke_cli.commands import flag_adapters as _adapters


AdapterFn = Callable[[List[str]], int]


SHEPHERD_SUBCOMMAND_REGISTRY: Dict[
    Tuple[str, ...], Tuple[str, AdapterFn]
] = {
    ("shepherd", "verdict"):
        ("shepherd.verdict.run", _adapters.shepherd_verdict),
    ("shepherd", "caveat-disposition"):
        ("shepherd.caveat_disposition.run",
         _adapters.shepherd_caveat_disposition),
}


__all__ = ["SHEPHERD_SUBCOMMAND_REGISTRY"]
