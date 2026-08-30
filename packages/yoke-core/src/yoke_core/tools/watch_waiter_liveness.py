"""Best-effort control-plane arm/completion calls for watcher wrappers."""

from __future__ import annotations

from typing import Any
from uuid import uuid4


def _ambient_session_id() -> str:
    try:
        from yoke_core.domain.session_ambient_identity import (
            resolve_ambient_session_id,
        )

        return str(resolve_ambient_session_id() or "")
    except Exception:  # noqa: BLE001 - no session makes registration a no-op
        return ""


def _touch(session_id: str, waiter: dict[str, Any]) -> dict[str, Any] | None:
    """Dispatch one waiter mutation without making the watched work depend on it."""
    try:
        from yoke_contracts.api.function_call import ActorContext, TargetRef
        from yoke_core.api.service_client_structured_api_adapter import (
            call_dispatcher,
        )

        response = call_dispatcher(
            function_id="sessions.touch",
            target=TargetRef(kind="global"),
            payload={"background_waiter": waiter},
            actor=ActorContext(session_id=session_id),
            intent="background watcher liveness",
        )
    except Exception:  # noqa: BLE001 - the child command remains authoritative
        return None
    if not response.success:
        return None
    result = response.result or {}
    facts = result.get("background_waiter")
    return dict(facts) if isinstance(facts, dict) else None


def watched_fact(kind: str) -> str:
    """The durable fact one wrapper waits to learn, without storing argv."""
    normalized = str(kind or "command").strip().replace("-", "_")
    return f"watch_{normalized} completion"


def arm_watcher_wait(kind: str) -> str:
    """Arm the ambient session's waiter and return its compare-by-id token."""
    session_id = _ambient_session_id()
    if not session_id:
        return ""
    waiter_id = str(uuid4())
    facts = _touch(
        session_id,
        {
            "action": "arm",
            "waiter_id": waiter_id,
            "kind": str(kind or "command"),
            "watched_fact": watched_fact(kind),
        },
    )
    return waiter_id if facts and facts.get("waiter_id") == waiter_id else ""


def complete_watcher_wait(waiter_id: str) -> None:
    """Complete this wrapper's arm; a stale token cannot complete a successor."""
    session_id = _ambient_session_id()
    if session_id and waiter_id:
        _touch(
            session_id,
            {"action": "complete", "waiter_id": waiter_id},
        )


__all__ = [
    "arm_watcher_wait",
    "complete_watcher_wait",
    "watched_fact",
]
