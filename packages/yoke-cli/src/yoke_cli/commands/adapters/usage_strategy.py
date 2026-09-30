"""The ``strategy.*`` function-id -> usage-line map.

Split from :mod:`yoke_cli.commands.adapters.usage` for the authored-file
line cap, the same reason that facade splits its adapters. One family's
usage lines and the imports behind them stay together here, and the facade
merges this dict into the single map its callers read.
"""

from __future__ import annotations

from yoke_cli.commands.adapters.strategy import (
    STRATEGY_DOC_GET_USAGE,
    STRATEGY_DOC_LIST_USAGE,
)
from yoke_cli.commands.adapters.strategy_create import STRATEGY_DOC_CREATE_USAGE
from yoke_cli.commands.adapters.strategy_doc_section_write import (
    STRATEGY_DOC_SECTION_REPLACE_USAGE,
)
from yoke_cli.commands.adapters.strategy_doc_write import (
    STRATEGY_DOC_ARCHIVE_USAGE,
    STRATEGY_DOC_REPLACE_USAGE,
    STRATEGY_DOC_UNARCHIVE_USAGE,
)
from yoke_cli.commands.adapters.strategy_render import (
    STRATEGY_INGEST_USAGE,
    STRATEGY_RENDER_USAGE,
)
from yoke_cli.commands.adapters.strategy_seed_defaults import (
    STRATEGY_SEED_DEFAULTS_USAGE,
)

STRATEGY_USAGE: dict[str, str] = {
    "strategy.doc.list": STRATEGY_DOC_LIST_USAGE,
    "strategy.doc.get": STRATEGY_DOC_GET_USAGE,
    "strategy.doc.create": STRATEGY_DOC_CREATE_USAGE,
    "strategy.doc.replace": STRATEGY_DOC_REPLACE_USAGE,
    "strategy.doc.section_replace": STRATEGY_DOC_SECTION_REPLACE_USAGE,
    "strategy.doc.archive": STRATEGY_DOC_ARCHIVE_USAGE,
    "strategy.doc.unarchive": STRATEGY_DOC_UNARCHIVE_USAGE,
    "strategy.render.run": STRATEGY_RENDER_USAGE,
    "strategy.ingest.run": STRATEGY_INGEST_USAGE,
    "strategy.seed_defaults.run": STRATEGY_SEED_DEFAULTS_USAGE,
}


__all__ = ["STRATEGY_USAGE"]
