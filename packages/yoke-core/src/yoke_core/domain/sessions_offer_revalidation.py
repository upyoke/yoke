"""Offer revalidation, live-claim recovery, and within-chain skip memory.

Sibling of :mod:`yoke_core.domain.sessions_offer`. Owns the candidate
revalidation, live-claim holder lookup, skip recording, and terminal-reason
classification surface so the offer-ownership flow stays small.

Each helper takes the live read-write connection plus a normalized item
identity and operates on the per-session ``chain_skip_memory`` envelope
(written by :func:`yoke_core.domain.sessions_queries_chain.append_chain_skip_entry`).
"""

from __future__ import annotations

from typing import Any, Dict, Optional, Tuple

from . import db_backend
from .scheduler_events import emit_chain_budget_unused, emit_scheduler_offer_skipped
from .scheduler_skip_reasons import (
    SKIP_REASON_STALE_LIFECYCLE,
    SKIP_REASON_STALE_LIFECYCLE_POST_CLAIM,
)
from .sessions_queries_chain import append_chain_skip_entry


_SKIP_REASON_TO_TERMINAL = {
    SKIP_REASON_STALE_LIFECYCLE: "all_candidates_stale",
    SKIP_REASON_STALE_LIFECYCLE_POST_CLAIM: "all_candidates_stale",
    "live_claim_conflict": "all_candidates_blocked",
    "process_disabled_by_config": "all_candidates_disabled_process",
    "recoverable_substrate": "all_candidates_recoverable_substrate",
}


# terminal_reason (classify_terminal_reason output) -> WAIT wait_reason.
# Keep keys aligned with _SKIP_REASON_TO_TERMINAL values plus the empty-set
# and mixed-cause fallbacks classify_terminal_reason can produce.
_TERMINAL_REASON_TO_WAIT_REASON = {
    "all_candidates_blocked": "all_runnable_items_blocked_by_live_claims",
    "all_candidates_stale": "all_runnable_items_stale",
    "all_candidates_disabled_process": "all_runnable_items_disabled_process",
    "all_candidates_recoverable_substrate": "all_runnable_items_recoverable_substrate",
    "mixed_unavailable": "all_runnable_items_unavailable_mixed",
    "no_candidates": "no_actionable_work_on_frontier",
}


def _p(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def normalize_item_id(item_id: Any) -> Optional[int]:
    """Return the bare integer form of an item id, or None when unparseable."""
    if item_id is None:
        return None
    if isinstance(item_id, int):
        return item_id
    text = str(item_id).strip()
    if text.upper().startswith("YOK-"):
        text = text[4:]
    try:
        return int(text)
    except ValueError:
        return None


def revalidate_candidate_status(
    conn: Any,
    *,
    item_id: str,
    expected_status: str,
) -> Tuple[bool, Optional[str]]:
    """Confirm the candidate's DB status still matches the schedule snapshot.

    Between schedule computation and claim acquisition another
    actor may have moved the item forward (for example
    ``polishing-implementation`` -> ``implemented``). Re-fetch the live
    status and compare against the snapshot recorded on the
    ``ScheduledStep``. Returns ``(is_valid, current_status)``. The
    candidate is invalid when the row is missing or the status changed.
    """
    bare = normalize_item_id(item_id)
    if bare is None:
        return False, None
    row = conn.execute(f"SELECT status FROM items WHERE id = {_p(conn)}", (bare,)).fetchone()
    if row is None:
        return False, None
    current = row[0]
    return current == expected_status, current


def holder_session_for_item(
    conn: Any,
    item_id: str,
) -> Dict[str, Any]:
    """Return canonical context about the live exclusive claim on ``item_id``.

    Skip events and ``/yoke do`` recovery
    summaries surface the canonical claim facts (``claim_id``,
    ``holder_session_id``, ``item_id``, ``claim_type``, ``claimed_at``)
    so reviewers do not need to hand-query ``work_claims``. The query
    is the same shape ``runtime.harness.harness_sessions_claims.cmd_who_claims``
    uses (the canonical surface exposed via
    ``python3 -m yoke_core.cli.db_router harness-sessions who-claims YOK-N``);
    keeping the column set in sync keeps both surfaces consistent.

    Returns ``{"holder_unknown": True}`` when no live claim row is found
    (the lookup may race against release).
    """
    bare = normalize_item_id(item_id)
    if bare is None:
        return {}
    row = conn.execute(
        """SELECT session_id, id, claimed_at, claim_type, item_id FROM work_claims
           WHERE target_kind = 'item' AND item_id = {p}
                 AND claim_type = 'exclusive'
                 AND released_at IS NULL
           ORDER BY claimed_at DESC, id DESC LIMIT 1""".format(p=_p(conn)),
        (bare,),
    ).fetchone()
    if row is None:
        return {"holder_unknown": True}
    keys = row.keys() if hasattr(row, "keys") else None
    if keys and "session_id" in keys:
        return {
            "holder_session_id": row["session_id"],
            "claim_id": row["id"],
            "claimed_at": row["claimed_at"],
            "claim_type": row["claim_type"],
            "item_id": row["item_id"],
        }
    return {
        "holder_session_id": row[0],
        "claim_id": row[1],
        "claimed_at": row[2],
        "claim_type": row[3],
        "item_id": row[4],
    }


def record_offer_skip(
    conn: Any,
    *,
    session_id: str,
    item_id: str,
    skip_reason: str,
    chain_step: int,
    project: str,
    expected_status: Optional[str],
    current_status: Optional[str],
    expected_next_step: Optional[str],
    holder_context: Optional[Dict[str, Any]] = None,
) -> None:
    """Append the skip to chain memory and emit ``SchedulerOfferSkipped``.

    The chain-skip memory entry deduplicates the candidate
    against later offers in the same chain; the audit event surfaces the
    reason, holder context, and expected vs current status so reviewers
    can trace the path through ``/yoke do``.
    """
    holder = holder_context or {}
    entry: Dict[str, Any] = {
        "item_id": str(item_id),
        "skip_reason": skip_reason,
        "chain_step": chain_step,
    }
    if expected_status is not None:
        entry["expected_status"] = expected_status
    if current_status is not None:
        entry["current_status"] = current_status
    if expected_next_step is not None:
        entry["expected_next_step"] = expected_next_step
    if holder.get("holder_session_id"):
        entry["claim_holder_session_id"] = holder["holder_session_id"]
    if holder.get("claim_id") is not None:
        entry["claim_id"] = holder["claim_id"]
    if holder.get("claimed_at"):
        entry["claimed_at"] = holder["claimed_at"]
    if holder.get("claim_type"):
        entry["claim_type"] = holder["claim_type"]
    if holder.get("holder_unknown"):
        entry["holder_unknown"] = True
    append_chain_skip_entry(conn, session_id, entry)

    extra: Dict[str, Any] = {}
    if expected_status:
        extra["expected_status"] = expected_status
    if holder.get("claim_type"):
        extra["claim_type"] = holder["claim_type"]
    if holder.get("holder_unknown"):
        extra["holder_unknown"] = True
    emit_scheduler_offer_skipped(
        session_id=session_id,
        skip_reason=skip_reason,
        chain_step=chain_step,
        project=project,
        item_id=str(item_id),
        recommended_action=expected_next_step,
        current_status=current_status,
        holder_session_id=holder.get("holder_session_id"),
        claim_id=holder.get("claim_id"),
        claimed_at=holder.get("claimed_at"),
        extra=extra or None,
    )


def classify_terminal_reason(skip_entries: list[Dict[str, Any]]) -> str:
    """Map a set of skip reasons recorded in one chain step to a terminal reason.

    When ``session_offer_with_ownership`` finishes without a
    claim, the offer is non-chainable for this step. The terminal reason
    distinguishes "all candidates were stale" from "all live-claimed",
    "all blocked behind disabled process work", "all recoverable substrate
    re-entry failures", and the mixed case. ``no_candidates`` is the empty-
    set case (no candidates were even attempted, e.g. scheduler returned
    nothing) and is reported separately so the caller can tell "skipped to
    exhaustion" from "had nothing to skip in the first place".
    """
    if not skip_entries:
        return "no_candidates"
    reasons = {entry.get("skip_reason") for entry in skip_entries}
    if len(reasons) == 1:
        only = next(iter(reasons))
        return _SKIP_REASON_TO_TERMINAL.get(only, "mixed_unavailable")
    return "mixed_unavailable"


_TRAIL_OPTIONAL_KEYS = (
    "expected_status",
    "current_status",
    "expected_next_step",
    "claim_holder_session_id",
    "claim_id",
    "claimed_at",
    "claim_type",
    "holder_unknown",
    "process_key",
    "config_key",
    "remediation_owner",
    "failure_class",
)


def _compact_skip_entry(entry: Dict[str, Any]) -> Dict[str, Any]:
    compact: Dict[str, Any] = {
        "item_id": entry.get("item_id"),
        "skip_reason": entry.get("skip_reason"),
    }
    for key in _TRAIL_OPTIONAL_KEYS:
        if key in entry:
            compact[key] = entry[key]
    return compact


def map_terminal_reason_to_wait_reason(terminal_reason: Optional[str]) -> str:
    """Translate a classified ``terminal_reason`` into a wait_reason label."""
    if not terminal_reason:
        return "no_actionable_work_on_frontier"
    return _TERMINAL_REASON_TO_WAIT_REASON.get(
        terminal_reason, "no_actionable_work_on_frontier"
    )


def build_no_work_wait_context(
    *,
    terminal_reason: Optional[str],
    skip_memory: list[Dict[str, Any]],
    chain_step: int,
    lane_filtered_count: int = 0,
    lane_filtered_items: Optional[list[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """Assemble the WAIT NextAction context for the ``action_hint=no_work`` path.

    ``cmd_session_offer`` honors ``ownership["action_hint"] ==
    "no_work"`` by constructing a WAIT directly rather than running
    ``decide_next_action`` over the unfiltered schedule. The context carries
    the classified ``terminal_reason`` and ``wait_reason``, the per-step skip
    trail (so reviewers do not need to re-query events), the live-claim
    holder ids when the only blocker is ``live_claim_conflict``, and the
    standard lane-filtered signals.
    """
    this_step_entries = [
        e for e in skip_memory if e.get("chain_step") == chain_step
    ]
    summary = [_compact_skip_entry(e) for e in this_step_entries]
    holder_ids: list[str] = []
    seen: set[str] = set()
    for e in this_step_entries:
        h = e.get("claim_holder_session_id")
        if h and h not in seen:
            seen.add(h)
            holder_ids.append(h)

    ctx: Dict[str, Any] = {
        "wait_reason": map_terminal_reason_to_wait_reason(terminal_reason),
        "terminal_reason": terminal_reason or "no_candidates",
        "chain_step": chain_step,
    }
    if summary:
        ctx["chain_skip_summary"] = summary
    if terminal_reason == "all_candidates_blocked" and holder_ids:
        ctx["holder_session_ids"] = sorted(holder_ids)
    if lane_filtered_count:
        ctx["lane_filtered_count"] = lane_filtered_count
        if lane_filtered_items:
            ctx["lane_filtered_items"] = list(lane_filtered_items)
    return ctx


def emit_chain_budget_unused_if_remaining(
    *,
    session_id: str,
    chain_step: int,
    max_chain_steps: int,
    skip_memory: list[Dict[str, Any]],
    project: str,
) -> Optional[str]:
    """Emit ``ChainBudgetUnused`` on a non-chainable offer with budget left.

    Filters ``skip_memory`` to entries from this chain step, classifies the
    terminal reason, and emits ``ChainBudgetUnused`` only when the offer
    consumed strictly less than the configured chain budget. The candidate
    trail attached to the event is the per-step skip slice so reviewers can
    see exactly which items were tried and why.

    Returns the ``terminal_reason`` so the caller can attach it to the
    offer return dict; returns ``None`` when there are no skip
    entries this step (the caller treats that as a no-candidates scheduler
    outcome and does not classify a terminal reason).
    """
    this_step_entries = [
        entry for entry in skip_memory
        if entry.get("chain_step") == chain_step
    ]
    if not this_step_entries:
        return None
    terminal_reason = classify_terminal_reason(this_step_entries)
    remaining_budget = max(0, max_chain_steps - chain_step)
    if remaining_budget <= 0:
        return terminal_reason
    candidate_trail = [_compact_skip_entry(e) for e in this_step_entries]
    emit_chain_budget_unused(
        session_id=session_id,
        step=chain_step,
        max_chain_steps=max_chain_steps,
        remaining_budget=remaining_budget,
        terminal_reason=terminal_reason,
        candidate_trail=candidate_trail,
        project=project,
    )
    return terminal_reason
