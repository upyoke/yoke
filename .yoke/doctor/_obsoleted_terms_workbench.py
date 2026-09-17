"""Workbench surfaces the focus-page split retired.

One Overview page used to stack Strategy, Frontier and Shipping under
collapsible bands. Each is its own destination now, so the route, the view
module, and the two loaders that existed only for that page are gone. The
shared card and band vocabulary they used lives on under names that say what
it is rather than which page it was built for.
"""

from __future__ import annotations

#: The view module and the loaders that had no other caller.
RETIRED_OVERVIEW_VIEW_MODULE_PATTERN = (
    r"universe_(?:views_overview\.js|overview_(?:strategy|sessions)\.js)"
)

#: Module names that moved with their subject: band primitives, work cards,
#: frontier bands, shipping runs, and the onboarding module stack.
RETIRED_OVERVIEW_MODULE_PATTERN = (
    r"universe_(?:overview_(?:primitives|cards|frontier|delivery)"
    r"|views_overview_activation)\b"
)

#: The route itself. An unrecognised hash already falls back to the first
#: destination, so the removal needed no alias. The page name is split so the
#: pattern cannot match its own declaration: the residue scan reads this
#: catalogue too, and a self-matching entry reports itself forever.
RETIRED_OVERVIEW_ROUTE_PATTERN = r"\#/" + "over" + r"view\b"

WORKBENCH_RETIREMENT_PATTERNS: tuple[str, ...] = (
    RETIRED_OVERVIEW_VIEW_MODULE_PATTERN,
    RETIRED_OVERVIEW_MODULE_PATTERN,
    RETIRED_OVERVIEW_ROUTE_PATTERN,
)

WORKBENCH_RETIREMENT_LABELS: dict[str, str] = {
    RETIRED_OVERVIEW_VIEW_MODULE_PATTERN: (
        "retired Overview view module (Strategy, Frontier and Shipping are "
        "each their own destination)"
    ),
    RETIRED_OVERVIEW_MODULE_PATTERN: (
        "retired Overview module name (band primitives, work cards, frontier "
        "bands, shipping runs, onboarding modules)"
    ),
    RETIRED_OVERVIEW_ROUTE_PATTERN: (
        "retired Overview route (an unrecognised hash falls back to Strategy)"
    ),
}

__all__ = [
    "RETIRED_OVERVIEW_MODULE_PATTERN",
    "RETIRED_OVERVIEW_ROUTE_PATTERN",
    "RETIRED_OVERVIEW_VIEW_MODULE_PATTERN",
    "WORKBENCH_RETIREMENT_LABELS",
    "WORKBENCH_RETIREMENT_PATTERNS",
]
