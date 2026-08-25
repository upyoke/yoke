"""Registered event vocabulary for document-led execution."""

CLAIM_ACQUIRED_EVENT = "StrategyDocClaimAcquired"
CLAIM_RELEASED_EVENT = "StrategyDocClaimReleased"
CLAIM_BREAK_GLASS_EVENT = "StrategyDocClaimBreakGlassReleased"
REVISION_RESTORED_EVENT = "StrategyDocRevisionRestored"
COORDINATION_APPENDED_EVENT = "StrategyDocCoordinationAppended"

STRATEGY_EXECUTION_EVENT_ROWS = (
    (
        CLAIM_ACQUIRED_EVENT,
        "A Blitz item or a session took the claim on a strategy document.",
    ),
    (
        CLAIM_RELEASED_EVENT,
        "A Blitz item or a session released its strategy-document claim.",
    ),
    (
        CLAIM_BREAK_GLASS_EVENT,
        "An operator released a stranded execution-document claim with rationale.",
    ),
    (
        REVISION_RESTORED_EVENT,
        "Old strategy content was restored by appending a new immutable revision.",
    ),
    (
        COORDINATION_APPENDED_EVENT,
        "A Slice Log or Live Status entry was appended without revising plan prose.",
    ),
)

__all__ = [
    "CLAIM_ACQUIRED_EVENT",
    "CLAIM_BREAK_GLASS_EVENT",
    "CLAIM_RELEASED_EVENT",
    "COORDINATION_APPENDED_EVENT",
    "REVISION_RESTORED_EVENT",
    "STRATEGY_EXECUTION_EVENT_ROWS",
]
