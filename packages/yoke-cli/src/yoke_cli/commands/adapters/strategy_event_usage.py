"""Usage map for strategy/event/Ouroboros adapter additions."""

from __future__ import annotations

from typing import Dict

from yoke_cli.commands.adapters.events import EVENTS_EMIT_USAGE
from yoke_cli.commands.adapters.ouroboros_writes import (
    OUROBOROS_ENTRY_INSERT_USAGE,
    OUROBOROS_ENTRY_MARK_ARCHIVED_USAGE,
    OUROBOROS_ENTRY_MARK_REVIEWED_USAGE,
    OUROBOROS_WRAPUP_LIST_USAGE,
)
from yoke_cli.commands.adapters.strategy_ops import (
    STRATEGY_CARRY_CANDIDATE_SET_USAGE,
    STRATEGY_CARRY_MARK_USAGE,
    STRATEGY_CARRY_REGISTER_NEW_USAGE,
    STRATEGY_CARRY_SUMMARY_USAGE,
    STRATEGY_CHECKPOINT_LATEST_USAGE,
    STRATEGY_CHECKPOINT_RECORD_USAGE,
    STRATEGY_MASTER_PLAN_CHECK_USAGE,
)


USAGE_BY_FUNCTION_ID: Dict[str, str] = {
    "events.emit": EVENTS_EMIT_USAGE,
    "ouroboros.entry.insert": OUROBOROS_ENTRY_INSERT_USAGE,
    "ouroboros.entry.mark_reviewed": OUROBOROS_ENTRY_MARK_REVIEWED_USAGE,
    "ouroboros.entry.mark_archived": OUROBOROS_ENTRY_MARK_ARCHIVED_USAGE,
    "ouroboros.wrapup.list": OUROBOROS_WRAPUP_LIST_USAGE,
    "strategy.carry.register_new": STRATEGY_CARRY_REGISTER_NEW_USAGE,
    "strategy.carry.candidate_set": STRATEGY_CARRY_CANDIDATE_SET_USAGE,
    "strategy.carry.summary": STRATEGY_CARRY_SUMMARY_USAGE,
    "strategy.carry.mark": STRATEGY_CARRY_MARK_USAGE,
    "strategy.checkpoint.record": STRATEGY_CHECKPOINT_RECORD_USAGE,
    "strategy.checkpoint.latest": STRATEGY_CHECKPOINT_LATEST_USAGE,
    "strategy.master_plan_check.run": STRATEGY_MASTER_PLAN_CHECK_USAGE,
}


__all__ = ["USAGE_BY_FUNCTION_ID"]
