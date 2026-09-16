"""Render-family CLI routes: agent adapters, packets, and the board view.

Split from :mod:`registry`, which is at the authored-file line cap. Every
route here renders or measures a generated surface rather than mutating
control-plane state, so they share one home.
"""

from __future__ import annotations

from typing import Callable, Dict, List, Tuple

from yoke_cli.commands import flag_adapters as _adapters
from yoke_cli.commands.adapters.packets import (
    packets_budget_get,
    packets_check,
    packets_render,
    packets_startup_delivery_get,
)


AdapterFn = Callable[[List[str]], int]

RENDER_SUBCOMMAND_REGISTRY: Dict[Tuple[str, ...], Tuple[str, AdapterFn]] = {
    ("agents", "render"): ("agents.render.run", _adapters.agents_render),
    ("agents", "render", "check"): (
        "agents.render.check",
        _adapters.agents_render_check,
    ),
    ("packets", "render"): ("packets.render.run", packets_render),
    ("packets", "check"): ("packets.check.run", packets_check),
    ("packets", "budget", "get"): ("packets.budget.get", packets_budget_get),
    ("packets", "startup-delivery", "get"): (
        "packets.startup_delivery.get",
        packets_startup_delivery_get,
    ),
    ("board", "rebuild"): ("board.rebuild.run", _adapters.board_rebuild),
    ("board", "data", "get"): ("board.data.get", _adapters.board_data_get),
}


__all__ = ["RENDER_SUBCOMMAND_REGISTRY"]
