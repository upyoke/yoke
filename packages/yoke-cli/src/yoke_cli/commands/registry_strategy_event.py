"""Strategy/event/Ouroboros entries for the aggregate ``yoke`` registry."""

from __future__ import annotations


from typing import Callable, Dict, List, Tuple

from yoke_cli.commands import flag_adapters as _adapters
from yoke_cli.commands.adapters.performance import (
    performance_aggregate,
    performance_detail,
)


AdapterFn = Callable[[List[str]], int]


STRATEGY_EVENT_SUBCOMMAND_REGISTRY: Dict[Tuple[str, ...], Tuple[str, AdapterFn]] = {
    ("events", "performance", "aggregate"): (
        "events.performance.aggregate",
        performance_aggregate,
    ),
    ("events", "performance", "detail"): (
        "events.performance.detail",
        performance_detail,
    ),
    ("events", "emit"): ("events.emit", _adapters.events_emit),
    ("feedback", "review"): (
        "ouroboros.entry.mark_reviewed",
        _adapters.feedback_review,
    ),
    ("feedback", "archive"): (
        "ouroboros.entry.mark_archived",
        _adapters.feedback_archive,
    ),
    ("strategy", "carry", "register-new"): (
        "strategy.carry.register_new",
        _adapters.strategy_carry_register_new,
    ),
    ("strategy", "carry", "candidate-set"): (
        "strategy.carry.candidate_set",
        _adapters.strategy_carry_candidate_set,
    ),
    ("strategy", "carry", "summary"): (
        "strategy.carry.summary",
        _adapters.strategy_carry_summary,
    ),
    ("strategy", "carry", "mark"): (
        "strategy.carry.mark",
        _adapters.strategy_carry_mark,
    ),
    ("strategy", "checkpoint", "record"): (
        "strategy.checkpoint.record",
        _adapters.strategy_checkpoint_record,
    ),
    ("strategy", "checkpoint", "latest"): (
        "strategy.checkpoint.latest",
        _adapters.strategy_checkpoint_latest,
    ),
}


__all__ = ["STRATEGY_EVENT_SUBCOMMAND_REGISTRY"]
