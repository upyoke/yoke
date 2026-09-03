"""Human summaries for session-roster diagnostic facts."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime, timezone
from typing import Any

from yoke_contracts.session_control.launch_registration import (
    LAUNCH_DELIVERY_PENDING_STATUS,
)


def _parse_time(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    candidate = f"{text[:-1]}+00:00" if text.endswith("Z") else text
    try:
        parsed = datetime.fromisoformat(candidate)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _age(value: Any, *, now: datetime | None = None) -> str:
    parsed = _parse_time(value)
    if parsed is None:
        return "unknown age"
    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    seconds = max(0, int((current - parsed).total_seconds()))
    if seconds < 60:
        return "now"
    minutes = seconds // 60
    if minutes < 60:
        return f"{minutes}m"
    hours = minutes // 60
    if hours < 48:
        return f"{hours}h"
    return f"{hours // 24}d"


def _latest_message(row: Mapping[str, Any]) -> str | None:
    message = row.get("latest_message")
    if not isinstance(message, Mapping):
        return None
    state = str(message.get("state") or "unknown").replace("_", " ")
    return f"message {state} {_age(message.get('created_at'))}"


def _end_blocker(row: Mapping[str, Any]) -> str | None:
    blocker = row.get("end_blocker")
    if not isinstance(blocker, Mapping):
        return None
    status = blocker.get("status")
    if status == "has_claims":
        return f"{int(blocker.get('active_claim_count') or 0)} claim(s) held"
    if status == "has_document_locks":
        count = int(blocker.get("active_document_lock_count") or 0)
        return f"{count} document lock(s) held"
    if status == "wake_delivery_in_flight":
        state = str(blocker.get("recipient_state") or "pending")
        return f"wake delivering ({state}) until {blocker.get('wake_delivery_window_ends_at')}"
    if status == LAUNCH_DELIVERY_PENDING_STATUS:
        launch = blocker.get("launch_id") or f"{blocker.get('launch_count')} launches"
        return f"launch {launch} binding until {blocker.get('binding_window_ends_at')}"
    if status == "chain_pending":
        step = int(blocker.get("checkpoint_step") or 0)
        maximum = int(blocker.get("max_chain_steps") or 0)
        return f"chain pending {step}/{maximum}"
    return str(status or "end blocked").replace("_", " ")


def _stale_context(row: Mapping[str, Any]) -> str | None:
    eligible = _parse_time(row.get("stale_eligible_at"))
    if eligible is None:
        return None
    now = datetime.now(timezone.utc)
    remaining = max(0, int((eligible - now).total_seconds() + 59) // 60)
    state = "stale-eligible now" if remaining == 0 else f"stale in {remaining}m"
    ttl = row.get("effective_stale_ttl_minutes")
    return f"{state} (TTL {ttl}m)" if ttl is not None else state


def roster_diagnostics(row: Mapping[str, Any]) -> str:
    """Render compact message, end-blocker, and stale-TTL context."""
    return "; ".join(
        part
        for part in (_latest_message(row), _end_blocker(row), _stale_context(row))
        if part
    )


__all__ = ["roster_diagnostics"]
