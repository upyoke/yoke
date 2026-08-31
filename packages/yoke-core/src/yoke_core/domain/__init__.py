"""Yoke domain layer — shared business logic for lifecycle, approvals, queries, runs, board, mutations, and session contracts.

Frontier, session, and dependency-planning names stay the public package
API but resolve on first attribute access so a short-lived ``db_router``
spawn that only needs ``db_backend`` does not load them.
"""

from __future__ import annotations

from importlib import import_module
from typing import Any

_EXPORTS: dict[str, tuple[str, str]] = {
    "DependencyEdge": (".dependencies", "DependencyEdge"),
    "GatePoint": (".dependencies", "GatePoint"),
    "GateResult": (".dependencies", "GateResult"),
    "Satisfaction": (".dependencies", "Satisfaction"),
    "evaluate_satisfaction": (".dependencies", "evaluate_satisfaction"),
    "explain_dependency": (".dependencies", "explain_dependency"),
    "query_frontier_blocks": (".dependencies", "query_frontier_blocks"),
    "query_unsatisfied_at_gate": (".dependencies", "query_unsatisfied_at_gate"),
    "BlockerDetail": (".dependency_planning", "BlockerDetail"),
    "CandidateItem": (".dependency_planning", "CandidateItem"),
    "ItemGateEvaluation": (".dependency_planning", "ItemGateEvaluation"),
    "PlanResult": (".dependency_planning", "PlanResult"),
    "evaluate_batch_gates": (".dependency_planning", "evaluate_batch_gates"),
    "evaluate_item_gate": (".dependency_planning", "evaluate_item_gate"),
    "plan_candidate_set": (".dependency_planning", "plan_candidate_set"),
    "AdapterCategory": (".frontier", "AdapterCategory"),
    "FrontierItem": (".frontier", "FrontierItem"),
    "FrontierResult": (".frontier", "FrontierResult"),
    "classify_next_action": (".frontier", "classify_next_action"),
    "compute_frontier": (".frontier", "compute_frontier"),
    "rank_frontier": (".frontier", "rank_frontier"),
    "ActionKind": (".session", "ActionKind"),
    "ClaimedWork": (".session", "ClaimedWork"),
    "FrontierState": (".session", "FrontierState"),
    "NextAction": (".session", "NextAction"),
    "NextActionKind": (".session", "NextActionKind"),
    "SessionOffer": (".session", "SessionOffer"),
    "decide_next_action": (".session", "decide_next_action"),
}


def __getattr__(name: str) -> Any:
    spec = _EXPORTS.get(name)
    if spec is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module_name, attr = spec
    value = getattr(import_module(module_name, __name__), attr)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(_EXPORTS))


__all__ = list(_EXPORTS)
