"""Mechanical CLI registry entries for workflow-aware item reads."""

from __future__ import annotations

from typing import Callable, Dict, List, Tuple

from yoke_cli.commands.adapters import item_pages


AdapterFn = Callable[[List[str]], int]
ITEM_PAGE_SUBCOMMAND_REGISTRY: Dict[
    Tuple[str, ...], Tuple[str, AdapterFn]
] = {
    ("items", "overview", "list"): (
        "items.overview.list",
        item_pages.items_overview_list,
    ),
    ("items", "detail", "get"): (
        "items.detail.get",
        item_pages.items_detail_get,
    ),
    ("items", "public-ref", "lookup"): (
        "items.public_ref.lookup",
        item_pages.items_public_ref_lookup,
    ),
}


__all__ = ["ITEM_PAGE_SUBCOMMAND_REGISTRY"]
