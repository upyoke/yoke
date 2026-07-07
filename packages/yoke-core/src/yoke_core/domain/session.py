"""Session-offer contract and next-action decision engine.

Refresh frontier facts, update stale frontier items, and materialize new work from the SML.
This front door preserves the public ``yoke_core.domain.session`` import path
while the implementation lives in responsibility-named siblings.

The decision engine is import-pure (no module-level ``os`` / ``sqlite3``
/ ``subprocess`` imports). The env-var probe for ``current_session_id``
lives in :mod:`yoke_core.api.service_client_shared_session_resolver`
(canonical ``session_identity`` cross-cutting entrypoint per
``AGENTS.md`` ``## Architecture Model``).
"""

from __future__ import annotations

from .session_contract import (
    ActionKind,
    ClaimedWork,
    FrontierState,
    NEXT_ACTION_CHOSEN_EVENT,
    NextAction,
    NextActionKind,
    SESSION_OFFERED_EVENT,
    SessionOffer,
    _CHAINABLE_ACTIONS,
)
from .session_decision import _NEXT_STEP_TO_PATH, decide_next_action
from .session_decision_context import _apply_lane_filtered_signal, _lane_filtered_note
from .session_decision_drift import (
    build_drift_review_failure_action,
    should_emit_drift_review_checkpoint,
)

__all__ = [
    "ActionKind",
    "NextActionKind",
    "SessionOffer",
    "NextAction",
    "SESSION_OFFERED_EVENT",
    "NEXT_ACTION_CHOSEN_EVENT",
    "ClaimedWork",
    "FrontierState",
    "_CHAINABLE_ACTIONS",
    "_lane_filtered_note",
    "_apply_lane_filtered_signal",
    "_NEXT_STEP_TO_PATH",
    "decide_next_action",
    "build_drift_review_failure_action",
    "should_emit_drift_review_checkpoint",
]
