"""Strategy/event/Ouroboros entries for the aggregate ``yoke`` registry."""

from __future__ import annotations

from typing import Callable, Dict, List, Tuple

from yoke_cli.commands import flag_adapters as _adapters


AdapterFn = Callable[[List[str]], int]


STRATEGY_EVENT_SUBCOMMAND_REGISTRY: Dict[
    Tuple[str, ...], Tuple[str, AdapterFn]
] = {
    ("events", "emit"):
        ("events.emit", _adapters.events_emit),
    ("ouroboros", "entry", "insert"):
        ("ouroboros.entry.insert", _adapters.ouroboros_entry_insert),
    ("ouroboros", "entry", "mark-reviewed"):
        ("ouroboros.entry.mark_reviewed",
         _adapters.ouroboros_entry_mark_reviewed),
    ("ouroboros", "entry", "mark-archived"):
        ("ouroboros.entry.mark_archived",
         _adapters.ouroboros_entry_mark_archived),
    ("ouroboros", "wrapup", "list"):
        ("ouroboros.wrapup.list", _adapters.ouroboros_wrapup_list),
    ("strategy", "carry", "register-new"):
        ("strategy.carry.register_new",
         _adapters.strategy_carry_register_new),
    ("strategy", "carry", "candidate-set"):
        ("strategy.carry.candidate_set",
         _adapters.strategy_carry_candidate_set),
    ("strategy", "carry", "summary"):
        ("strategy.carry.summary", _adapters.strategy_carry_summary),
    ("strategy", "carry", "mark"):
        ("strategy.carry.mark", _adapters.strategy_carry_mark),
    ("strategy", "checkpoint", "record"):
        ("strategy.checkpoint.record",
         _adapters.strategy_checkpoint_record),
    ("strategy", "checkpoint", "latest"):
        ("strategy.checkpoint.latest",
         _adapters.strategy_checkpoint_latest),
    ("strategy", "master-plan-check"):
        ("strategy.master_plan_check.run",
         _adapters.strategy_master_plan_check),
}


__all__ = ["STRATEGY_EVENT_SUBCOMMAND_REGISTRY"]
