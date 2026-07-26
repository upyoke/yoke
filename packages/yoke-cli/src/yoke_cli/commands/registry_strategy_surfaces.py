"""Mechanical registry entries for strategy review and execution surfaces."""

from __future__ import annotations

from typing import Callable, Dict, List, Tuple

from yoke_cli.commands.adapters import strategy_surfaces as adapters


AdapterFn = Callable[[List[str]], int]
STRATEGY_SURFACE_SUBCOMMAND_REGISTRY: Dict[
    Tuple[str, ...], Tuple[str, AdapterFn]
] = {
    tuple(function_id.replace("_", "-").split(".")): (
        function_id,
        getattr(adapters, function_id.replace(".", "_")),
    )
    for function_id in adapters.USAGE_BY_FUNCTION_ID
}


__all__ = ["STRATEGY_SURFACE_SUBCOMMAND_REGISTRY"]
