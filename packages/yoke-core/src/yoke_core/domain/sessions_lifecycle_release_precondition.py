"""Pre-mutation precondition for execution-owned work-claim releases.

A non-terminal ``release_reason_intent`` (e.g. ``readiness-check-blocked``)
means the holding session intends to resume on the item once its blocking
precondition clears. Releasing such a claim before the routed handler has
recorded a durable terminal checkpoint reproduces an incident.
The evaluator gates the release for item targets only — epic_task and
process targets carry no routed-handler frame semantics in ``/yoke do``.
A persisted chain checkpoint is "terminal evidence" when ``chainable=False``
OR ``handler_outcome`` is in :data:`TERMINAL_OUTCOMES`. A missing checkpoint
means the session never started a routed chain and the release is allowed.
The evaluator is a pure read on the caller's open ``conn``: no commit, no
rollback, no side effects beyond the chain-checkpoint SELECT.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional

from . import sessions_analytics as _sa
from .release_intent_classification import is_non_terminal_release_intent
from .sessions_handler_outcome import TERMINAL_OUTCOMES
from .sessions_queries_chain import read_chain_checkpoint
from .work_claim_targets import TARGET_KIND_ITEM, WorkClaimTarget


@dataclass(frozen=True)
class ReleasePreconditionResult:
    """Outcome of evaluating a release against the precondition.

    ``allowed=True`` when the release may proceed; otherwise
    ``refusal_reason`` names the refusal class. ``checkpoint_outcome`` /
    ``checkpoint_chainable`` echo the persisted chain checkpoint fields
    (``None`` when no checkpoint exists or when allowed via the
    early-exit branches that read no checkpoint).
    """

    allowed: bool
    refusal_reason: Optional[str] = None
    checkpoint_outcome: Optional[str] = None
    checkpoint_chainable: Optional[bool] = None


REFUSAL_NON_TERMINAL_RELEASE = "non_terminal_release_refused"

# Event names emitted by the precondition / operator-override flow.
# Defined here (rather than in ``sessions_analytics_core``) because this
# module owns both emission sites; ``populate_registry_data_authoritative``
# registers the matching event_registry rows by string literal.
EVENT_ITEM_CLAIM_RELEASE_REFUSED = "ItemClaimReleaseRefused"
EVENT_ITEM_CLAIM_RELEASE_OVERRIDE = "ItemClaimReleaseOverride"


def evaluate_release_precondition(
    conn: Any,
    *,
    session_id: str,
    target: WorkClaimTarget,
    release_reason_intent: Optional[str],
    allow_non_terminal: bool = False,
) -> ReleasePreconditionResult:
    """Evaluate whether a release may proceed.

    ``allow_non_terminal=True`` is the operator-override bypass — the
    evaluator returns ``allowed=True`` regardless of checkpoint state.
    Terminal intents (per :func:`is_non_terminal_release_intent`) and
    non-item targets short-circuit before any DB read. For item targets
    on a non-terminal intent, the evaluator reads the persisted chain
    checkpoint: ``chainable=False`` OR ``handler_outcome`` in
    :data:`TERMINAL_OUTCOMES` allows the release; a missing checkpoint
    also allows (no routed chain ever started); otherwise refuse.
    """
    if allow_non_terminal:
        return ReleasePreconditionResult(allowed=True)
    if not is_non_terminal_release_intent(release_reason_intent):
        return ReleasePreconditionResult(allowed=True)
    if target.kind != TARGET_KIND_ITEM:
        return ReleasePreconditionResult(allowed=True)

    checkpoint = read_chain_checkpoint(conn, session_id)
    if checkpoint is None:
        return ReleasePreconditionResult(allowed=True)

    raw_chainable = checkpoint.get("chainable")
    chainable = bool(raw_chainable) if raw_chainable is not None else None
    outcome = checkpoint.get("handler_outcome")
    outcome_str = str(outcome) if outcome is not None else None

    if chainable is False or outcome_str in TERMINAL_OUTCOMES:
        return ReleasePreconditionResult(
            allowed=True,
            checkpoint_outcome=outcome_str,
            checkpoint_chainable=chainable,
        )
    return ReleasePreconditionResult(
        allowed=False,
        refusal_reason=REFUSAL_NON_TERMINAL_RELEASE,
        checkpoint_outcome=outcome_str,
        checkpoint_chainable=chainable,
    )


def _target_item_id(target: WorkClaimTarget) -> Optional[str]:
    if target.kind == TARGET_KIND_ITEM and target.item_id is not None:
        return str(target.item_id)
    return None


def emit_release_refused(
    *,
    session_id: str,
    target: WorkClaimTarget,
    claim_id: int,
    reason: str,
    precondition: ReleasePreconditionResult,
) -> Dict[str, Any]:
    """Emit ``ItemClaimReleaseRefused`` and return the failure dict.

    Called when the precondition refuses a non-terminal release. The
    ``work_claims`` row is NOT mutated — the holding session keeps the
    claim and resumes on it once the routed handler reaches a durable
    terminal checkpoint. The envelope carries the cold-start
    evidence fields.
    """
    item_id_for_event = _target_item_id(target)
    envelope: Dict[str, Any] = {
        "prior_owner_session_id": session_id,
        "item_id": item_id_for_event,
        "claim_id": claim_id,
        "release_reason_intent": reason,
        "checkpoint_outcome": precondition.checkpoint_outcome,
        "checkpoint_chainable": precondition.checkpoint_chainable,
        "failure_reason": precondition.refusal_reason,
        "target_kind": target.kind,
        "target_label": target.render(),
    }
    _sa._emit_event(
        EVENT_ITEM_CLAIM_RELEASE_REFUSED,
        event_kind="system", event_type="session_lifecycle",
        source_type="backend", session_id=session_id,
        item_id=item_id_for_event, context=envelope,
        outcome="refused", severity="WARN",
    )
    return {
        "released": False,
        "failure_reason": precondition.refusal_reason,
        "checkpoint_outcome": precondition.checkpoint_outcome,
        "checkpoint_chainable": precondition.checkpoint_chainable,
        "release_reason_intent": reason,
        "target_kind": target.kind,
        "target_label": target.render(),
        "claim_id": claim_id,
    }


def emit_release_override(
    *,
    session_id: str,
    target: WorkClaimTarget,
    claim_id: int,
    reason: str,
    operator_rationale: str,
) -> None:
    """Emit ``ItemClaimReleaseOverride`` for an operator-supplied bypass.

    Records the operator's rationale alongside the bypassed release so
    triage can trace why a non-terminal release proceeded without
    checkpoint evidence.
    """
    item_id_for_event = _target_item_id(target)
    _sa._emit_event(
        EVENT_ITEM_CLAIM_RELEASE_OVERRIDE,
        event_kind="system", event_type="session_lifecycle",
        source_type="backend", session_id=session_id,
        item_id=item_id_for_event,
        context={
            "prior_owner_session_id": session_id,
            "item_id": item_id_for_event,
            "claim_id": claim_id,
            "release_reason_intent": reason,
            "operator_rationale": operator_rationale,
            "target_kind": target.kind,
            "target_label": target.render(),
        },
        outcome="completed", severity="WARN",
    )


__all__ = [
    "ReleasePreconditionResult",
    "REFUSAL_NON_TERMINAL_RELEASE",
    "EVENT_ITEM_CLAIM_RELEASE_REFUSED",
    "EVENT_ITEM_CLAIM_RELEASE_OVERRIDE",
    "evaluate_release_precondition",
    "emit_release_refused",
    "emit_release_override",
]
