"""SessionOfferInvariantFailed emitter — session-offer charge-invariant cleanup telemetry.

Owned by the session-offer charge-invariant cleanup path (CLI and HTTP).
The structured event makes the exact invariant-failure mismatch queryable
without scraping the generic harness tool output that previously held the
only diagnostic detail.

The payload tolerates ``new_claim`` being absent: the second invariant-failure
shape (charge action returned without a backing work claim) emits the event
with null claim fields while still preserving the invariant_message.
"""

from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional

from yoke_core.domain.session_contract import NextAction
from yoke_core.domain.sessions_analytics_core import _emit_event
from yoke_core.domain.sessions_queries_base import normalize_claim_item_id


def _summarise_skip_memory(skip_memory: Iterable[Any]) -> List[Dict[str, Any]]:
    summary: List[Dict[str, Any]] = []
    for entry in skip_memory or []:
        if not isinstance(entry, dict):
            continue
        raw_item_id = entry.get("item_id")
        normalized_item_id = (
            normalize_claim_item_id(str(raw_item_id)) if raw_item_id else raw_item_id
        )
        summary.append(
            {
                "item_id": normalized_item_id,
                "reason": entry.get("reason") or entry.get("skip_reason"),
                "chain_step": entry.get("chain_step"),
            }
        )
    return summary


def _summarise_new_claim(new_claim: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if not new_claim:
        return None
    return {
        "claim_id": new_claim.get("id") or new_claim.get("claim_id"),
        "item_id": new_claim.get("item_id"),
    }


def _resolve_item_id_for_index(
    new_claim_payload: Optional[Dict[str, Any]],
    selected_item: Any,
) -> Optional[str]:
    """Pick the indexed item id for the event row.

    Prefer the new_claim's item_id (numeric, authoritative). Fall back to
    the YOK-N-prefixed selected_item when the claim is absent (the second
    invariant-failure shape).
    """
    if new_claim_payload and new_claim_payload.get("item_id") is not None:
        return str(new_claim_payload["item_id"])
    if not selected_item:
        return None
    try:
        return str(int(str(selected_item).replace("YOK-", "")))
    except (ValueError, AttributeError):
        return None


def emit_session_offer_invariant_failed(
    *,
    session_id: str,
    result: NextAction,
    new_claim: Optional[Dict[str, Any]],
    ownership: Optional[Dict[str, Any]] = None,
    invariant_message: str,
    surface: str,
    release_outcome: Optional[Dict[str, Any]] = None,
    project: str = "yoke",
) -> None:
    """Emit SessionOfferInvariantFailed for an aborted charge offer.

    Records action, selected_item, schedule_selected_item, new_claim
    {claim_id, item_id}, retry_skip_summary, invariant_message, surface,
    and (optionally) the release_outcome so subsequent diagnostics can
    query the domain event directly.
    """
    ctx = result.context or {}
    selected_item = ctx.get("selected_item")
    scheduler_block = ctx.get("scheduler")
    schedule_selected_item: Optional[Any] = None
    if isinstance(scheduler_block, dict):
        schedule_selected_item = (
            scheduler_block.get("selected_item")
            or scheduler_block.get("item_id")
        )

    new_claim_payload = _summarise_new_claim(new_claim)
    skip_summary = _summarise_skip_memory(
        (ownership or {}).get("chain_skip_memory") or []
    )

    event_ctx: Dict[str, Any] = {
        "action": result.action.value,
        "selected_item": selected_item,
        "schedule_selected_item": schedule_selected_item,
        "new_claim": new_claim_payload,
        "retry_skip_summary": skip_summary,
        "invariant_message": invariant_message,
        "surface": surface,
    }
    if release_outcome is not None:
        event_ctx["release_outcome"] = release_outcome

    _emit_event(
        "SessionOfferInvariantFailed",
        event_kind="workflow",
        event_type="session_offer_invariant",
        source_type="backend",
        session_id=session_id,
        project=project,
        item_id=_resolve_item_id_for_index(new_claim_payload, selected_item),
        context=event_ctx,
        severity="WARN",
        outcome="failed",
    )


__all__ = ["emit_session_offer_invariant_failed"]
