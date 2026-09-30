"""The ``strategy.*`` family's adapter re-exports.

Split from :mod:`yoke_cli.commands.flag_adapters` for the authored-file
line cap, which is the same reason that facade imports every family from a
sibling module rather than defining them. The facade re-exports this
module's names, so a caller reaching for any strategy adapter still finds
it there.
"""

from __future__ import annotations

from yoke_cli.commands.adapters.strategy import strategy_doc_get, strategy_doc_list
from yoke_cli.commands.adapters.strategy_create import strategy_doc_create
from yoke_cli.commands.adapters.strategy_doc_write import (
    strategy_doc_archive, strategy_doc_replace, strategy_doc_unarchive,
)
from yoke_cli.commands.adapters.strategy_doc_section_write import (
    strategy_doc_section_replace,
)
from yoke_cli.commands.adapters.strategy_render import strategy_ingest, strategy_render
from yoke_cli.commands.adapters.strategy_seed_defaults import strategy_seed_defaults
from yoke_cli.commands.adapters.strategy_ops import (
    strategy_carry_candidate_set,
    strategy_carry_mark,
    strategy_carry_register_new,
    strategy_carry_summary,
    strategy_checkpoint_latest,
    strategy_checkpoint_record,
    strategy_master_plan_check,
)

__all__ = [
    "strategy_doc_list",
    "strategy_doc_get",
    "strategy_doc_create",
    "strategy_doc_replace",
    "strategy_doc_section_replace",
    "strategy_doc_archive",
    "strategy_doc_unarchive",
    "strategy_render",
    "strategy_ingest",
    "strategy_seed_defaults",
    "strategy_carry_register_new",
    "strategy_carry_candidate_set",
    "strategy_carry_summary",
    "strategy_carry_mark",
    "strategy_checkpoint_record",
    "strategy_checkpoint_latest",
    "strategy_master_plan_check",
]
