"""Handler-outcome classification for ``/yoke do`` chain accounting.

Routed handlers (``/yoke advance``,
``/yoke strategize``, future) report back to the chain via a discrete
``handler_outcome`` field on the chain checkpoint. ``/yoke do``'s
Step C reads the outcome and decides whether to bump the useful chain
step, preserve the work claim, or terminate the chain.

Outcomes:

- ``completed`` — the routed handler reached a lifecycle boundary (e.g.
  ``reviewed-implementation``); the chain step bumps and the loop may
  re-offer.
- ``slice_committed`` — the routed handler made internal progress (a
  commit, Progress Log entry, focused verification) but the item is
  still ``implementing``; the chain step does NOT bump and the
  loop continues with the same item via resume.
- ``recoverable_substrate`` — the routed handler hit a recoverable
  advance-entry substrate failure (worktree scope drift, cwd binding
  drift, guard-compatible re-entry failure) before useful work began
  ; the step does NOT bump and the same item is dedup'd
  by chain skip memory so it is not reselected.
- ``interactive_checkpoint`` — an enabled process action (Strategize,
  Feed) reached an operator checkpoint; the work claim stays
  open intentionally and the chain is non-chainable so generic session
  cleanup does not release it.
- ``blocked`` — the handler hit a real non-recoverable blocker; the
  chain is non-chainable.

The chain summary surface in ``/yoke do`` consumes
:func:`render_chain_summary_label` so prose and runtime stay in sync.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from .scheduler_events import emit_scheduler_offer_skipped
from .sessions_queries_base import normalize_claim_item_id
from .sessions_queries_chain import append_chain_skip_entry, update_chain_checkpoint


OUTCOME_COMPLETED = "completed"
OUTCOME_SLICE_COMMITTED = "slice_committed"
OUTCOME_RECOVERABLE_SUBSTRATE = "recoverable_substrate"
OUTCOME_INTERACTIVE_CHECKPOINT = "interactive_checkpoint"
OUTCOME_BLOCKED = "blocked"


RELEASE_REASON_RECOVERABLE_SUBSTRATE_SKIP = "recoverable-substrate-skip"


# Maps a named substrate failure class to the handler_outcome recorded on
# the chain checkpoint. Entries cover known pre-fix substrate shapes; the
# classifier default handles novel classes safely.
SUBSTRATE_FAILURE_TAXONOMY = {
    # Uncommitted files on main blocking worktree creation. Operator can
    # commit/stash; next chain offer can retry the same item.
    "dirty-tracked-main": OUTCOME_RECOVERABLE_SUBSTRATE,
    # Planning-phase write that the path-claim Bash guard previously
    # rejected before the worktree-binding guard was corrected.
    "unbound-worktree": OUTCOME_RECOVERABLE_SUBSTRATE,
    # Un-attested overlap with no `coordination_only` row. Requires
    # authoring decision; not a same-session retry.
    "path-claim-overlap-incompatible": OUTCOME_BLOCKED,
    # Coordination lease held by another live session. Lease releases on
    # the other session's completion; same-chain retry is plausible.
    "lease-conflict": OUTCOME_RECOVERABLE_SUBSTRATE,
}


def classify_substrate_failure(failure_class: Optional[str]) -> str:
    """Map a substrate failure class to a chain checkpoint outcome.

    Returns the taxonomy entry when present, else ``OUTCOME_BLOCKED``. The
    default is intentionally conservative: novel classes are more likely
    than recurrences of starter classes, and routing an unknown failure to
    ``blocked`` stops the chain (chainable=False) so the operator sees the
    unfamiliar failure rather than the loop silently re-offering it.
    """
    if not failure_class:
        return OUTCOME_BLOCKED
    return SUBSTRATE_FAILURE_TAXONOMY.get(failure_class, OUTCOME_BLOCKED)


# Slice commits and recoverable substrate failures must
# not consume useful chain budget.
NON_USEFUL_STEP_OUTCOMES = frozenset({
    OUTCOME_SLICE_COMMITTED,
    OUTCOME_RECOVERABLE_SUBSTRATE,
})


# Outcomes that imply ``chainable=False`` on the chain checkpoint.
TERMINAL_OUTCOMES = frozenset({
    OUTCOME_INTERACTIVE_CHECKPOINT,
    OUTCOME_BLOCKED,
})


# Operator-facing labels for each outcome. The chain
# summary block in ``/yoke do`` reads this map; prose and tests
# reference the constants so a label change requires one edit.
_OUTCOME_LABELS = {
    OUTCOME_COMPLETED: "handler completed",
    OUTCOME_SLICE_COMMITTED: "implementation slice committed; handler continuing",
    OUTCOME_RECOVERABLE_SUBSTRATE: "recoverable substrate failure; handler continuing",
    OUTCOME_INTERACTIVE_CHECKPOINT: "interactive checkpoint active",
    OUTCOME_BLOCKED: "handler blocked",
}


def is_non_useful_step(handler_outcome: Optional[str]) -> bool:
    """Whether ``/yoke do`` should leave the useful step counter unchanged."""
    if not handler_outcome:
        return False
    return handler_outcome in NON_USEFUL_STEP_OUTCOMES


def is_terminal_outcome(handler_outcome: Optional[str]) -> bool:
    """Whether the chain MUST stop after this outcome (chainable=False)."""
    if not handler_outcome:
        return False
    return handler_outcome in TERMINAL_OUTCOMES


def classify_advance_outcome(
    *,
    pre_status: str,
    post_status: str,
    action: str = "advance",
) -> str:
    """Classify a routed advance handler outcome from item statuses.

    When the advance handler returns and the item's
    status remained ``implementing`` (or whichever status the action had
    targeted), the handler made a slice but did not reach a lifecycle
    boundary -> ``slice_committed`` (no step bump).

    When the post-status is a different lifecycle status from the pre-
    status (handler crossed a boundary) -> ``completed``.

    The classifier is a pure function so it can be unit-tested without
    touching the DB. ``action`` is currently informational; it is
    accepted so future actions (charge, resume, polish) can plug into
    the same classifier without changing the call site.
    """
    if not post_status:
        return OUTCOME_COMPLETED
    if post_status == pre_status and post_status == "implementing":
        return OUTCOME_SLICE_COMMITTED
    return OUTCOME_COMPLETED


def record_recoverable_substrate_skip(
    conn: Any,
    *,
    session_id: str,
    chain_step: int,
    project: str,
    item_id: Optional[str],
    routed_action: str,
    failure_class: str,
    remediation_owner: str,
    current_status: Optional[str] = None,
    useful_work_began: bool = False,
) -> Dict[str, Any]:
    """Record a recoverable advance-entry substrate failure.

    The routed handler reports a recoverable substrate failure
    with structured context.

    The chain skip memory entry deduplicates the failed item so
    the next offer in the same chain does not re-select it.

    ``failure_class`` and ``remediation_owner`` flow into the
    ``SchedulerOfferSkipped`` event and the chain summary candidate
    trail so the terminal stop reason names the owner.

    Returns the chain-skip-memory entry that was persisted so callers
    can echo it into the chain checkpoint or operator summary.
    """
    entry: Dict[str, Any] = {
        "skip_reason": "recoverable_substrate",
        "chain_step": chain_step,
        "routed_action": routed_action,
        "failure_class": failure_class,
        "remediation_owner": remediation_owner,
        "useful_work_began": useful_work_began,
    }
    normalized_item_id = (
        normalize_claim_item_id(str(item_id)) if item_id is not None else None
    )
    if normalized_item_id is not None:
        entry["item_id"] = normalized_item_id
    if current_status is not None:
        entry["current_status"] = current_status
    append_chain_skip_entry(conn, session_id, entry)

    if normalized_item_id is not None:
        # Lazy import: ``sessions_lifecycle_release_precondition`` imports
        # ``TERMINAL_OUTCOMES`` from this module, so a top-level import would
        # create a circular dependency at module load time.
        from .sessions_lifecycle_release import release_item_claim_for_execution

        try:
            release_item_claim_for_execution(
                conn,
                session_id,
                normalized_item_id,
                RELEASE_REASON_RECOVERABLE_SUBSTRATE_SKIP,
            )
        except Exception:
            pass

    emit_scheduler_offer_skipped(
        session_id=session_id,
        skip_reason="recoverable_substrate",
        chain_step=chain_step,
        project=project,
        item_id=normalized_item_id,
        recommended_action=routed_action,
        current_status=current_status,
        extra={
            "failure_class": failure_class,
            "remediation_owner": remediation_owner,
            "useful_work_began": useful_work_began,
        },
    )
    return entry


def record_interactive_checkpoint_handoff(
    conn: Any,
    *,
    session_id: str,
    step: int,
    process_key: str,
    item_id: Optional[str] = None,
    checkpoint_label: Optional[str] = None,
) -> Dict[str, Any]:
    """Record an interactive operator checkpoint on the chain checkpoint.

    An enabled process action (Strategize, Feed, future) reached
    an operator checkpoint. The chain checkpoint records
    ``handler_outcome=interactive_checkpoint`` and ``chainable=False``.
    The caller is responsible for NOT releasing the process work claim
    so resume / abort / complete can be handled through the process
    skill's own checkpoint contract.

    The chain summary distinguishes this state from
    ``handler completed`` via :func:`render_chain_summary_label`.

    Returns the persisted chain checkpoint dict.
    """
    return update_chain_checkpoint(
        conn,
        session_id,
        step=step,
        action=process_key,
        chainable=False,
        handler_outcome=OUTCOME_INTERACTIVE_CHECKPOINT,
        item_id=item_id,
        status=checkpoint_label,
    )


def render_chain_summary_label(handler_outcome: Optional[str]) -> str:
    """Map a handler outcome to the operator-facing chain summary label.

    ``/yoke do``'s end-of-step summary reads this label
    so an ``implementation slice committed`` is never reported as
    ``CHAIN STEP N/M COMPLETE``. Unknown outcomes fall back to the
    completed label so older callers stay safe.
    """
    return _OUTCOME_LABELS.get(handler_outcome or "", _OUTCOME_LABELS[OUTCOME_COMPLETED])


__all__ = [
    "OUTCOME_COMPLETED",
    "OUTCOME_SLICE_COMMITTED",
    "OUTCOME_RECOVERABLE_SUBSTRATE",
    "OUTCOME_INTERACTIVE_CHECKPOINT",
    "OUTCOME_BLOCKED",
    "RELEASE_REASON_RECOVERABLE_SUBSTRATE_SKIP",
    "SUBSTRATE_FAILURE_TAXONOMY",
    "NON_USEFUL_STEP_OUTCOMES",
    "TERMINAL_OUTCOMES",
    "classify_substrate_failure",
    "is_non_useful_step",
    "is_terminal_outcome",
    "classify_advance_outcome",
    "record_recoverable_substrate_skip",
    "record_interactive_checkpoint_handoff",
    "render_chain_summary_label",
]
