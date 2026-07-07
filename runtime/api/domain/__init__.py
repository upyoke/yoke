"""Yoke domain layer — shared business logic for lifecycle, approvals, queries, runs, board, mutations, and session contracts."""

from yoke_core.domain.dependencies import (  # noqa: F401 — re-export public API
    DependencyEdge,
    GatePoint,
    GateResult,
    Satisfaction,
    evaluate_satisfaction,
    explain_dependency,
    query_frontier_blocks,
    query_unsatisfied_at_gate,
)
from yoke_core.domain.dependency_planning import (  # noqa: F401 — re-export public API
    BlockerDetail,
    CandidateItem,
    ItemGateEvaluation,
    PlanResult,
    evaluate_batch_gates,
    evaluate_item_gate,
    plan_candidate_set,
)
from yoke_core.domain.frontier import (  # noqa: F401 — re-export public API
    AdapterCategory,
    FrontierItem,
    FrontierResult,
    classify_next_action,
    compute_frontier,
    rank_frontier,
)
from yoke_core.domain.session import (  # noqa: F401 — re-export public API
    ActionKind,
    ClaimedWork,
    FrontierState,
    NextAction,
    NextActionKind,
    SessionOffer,
    decide_next_action,
)
