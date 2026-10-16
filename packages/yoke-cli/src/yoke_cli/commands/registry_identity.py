"""Sign-in identity admin entries for the aggregate ``yoke`` registry."""

from __future__ import annotations

from typing import Callable, Dict, List, Tuple

from yoke_cli.commands import flag_adapters as _adapters


AdapterFn = Callable[[List[str]], int]


IDENTITY_SUBCOMMAND_REGISTRY: Dict[Tuple[str, ...], Tuple[str, AdapterFn]] = {
    ("identity", "link", "set"): ("identity.link.set", _adapters.identity_link_set),
}


__all__ = ["IDENTITY_SUBCOMMAND_REGISTRY"]
