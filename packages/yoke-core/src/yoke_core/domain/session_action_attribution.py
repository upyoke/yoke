"""Record who performed an action *on* a session, in that session's history.

A session's history is the event stream keyed on its own ``session_id``.
Everything a session does for itself already lands there, but everything
done *to* it — a message, a wake, a keep-alive hold, a termination, the
launch that started it — was recorded only under the *caller's* session,
so reading a session's history could never answer "who drove this, and
when". A worker that was woken by somebody else looked, from its own
history, exactly like one that woke up on its own.

This module closes that gap with one ``SessionActionPerformed`` row per
target session per dispatched session-affecting call. The row carries the
acting actor as its own ``actor_id`` (never the target's, which is what
the session-actor backfill would otherwise supply), the acting session,
the function id, and whether the call succeeded — so "done by <actor>"
is a read of the target's own history rather than a join nobody performs.

Emission is best-effort and never fails the call it describes: the action
already happened and its own handler recorded it, so a failure to write
the attribution row must not turn a completed termination into an error.
"""

from __future__ import annotations

from typing import Any, Dict, Iterable, Mapping, Optional

from yoke_contracts.api.function_call import (
    FunctionCallRequest,
    FunctionCallResponse,
)


EVENT_SESSION_ACTION_PERFORMED = "SessionActionPerformed"

#: Function id → the action name a reader sees. Membership in this table
#: is what makes a function "session-affecting": it is the one list the
#: attribution writer and the authority check
#: (:mod:`yoke_core.domain.session_action_authority`) both read, so the
#: set that is recorded and the set that is role-checked cannot drift.
SESSION_ACTION_LABELS: Dict[str, str] = {
    "session_control.message.send": "message",
    "session_control.session.wake": "wake",
    "session_control.session.terminate": "terminate",
    "session_control.keepalive.hold": "keepalive hold",
    "session_control.keepalive.release": "keepalive release",
    "session_control.launch.create": "launch",
    "session_control.launch.retry": "launch retry",
    "session_control.launch.reconcile": "launch reconcile",
}


def action_label(function_id: str) -> Optional[str]:
    """Return the reader-facing action name, or ``None`` when not one."""
    return SESSION_ACTION_LABELS.get(function_id)


def _text(value: Any) -> str:
    return str(value).strip() if isinstance(value, (str, int)) else ""


def _ordered_unique(candidates: Iterable[str]) -> tuple[str, ...]:
    seen: list[str] = []
    for candidate in candidates:
        text = _text(candidate)
        if text and text not in seen:
            seen.append(text)
    return tuple(seen)


def target_session_ids(
    function_id: str,
    payload: Mapping[str, Any],
    result: Mapping[str, Any],
) -> tuple[str, ...]:
    """Return the sessions this call acted on, in the order it named them.

    Both halves are read because neither alone is complete: a caller may
    name a target directly (``session_id`` in the payload) or by anchor
    (a message's audience, a wake's item ref), and only the result names
    what the anchor resolved to. A launch names a session only once its
    worker has registered, so a create that has not yet bound one
    contributes nothing here — the launch row already carries the
    requesting actor, and the worker inherits it at registration.
    """
    if function_id not in SESSION_ACTION_LABELS:
        return ()
    candidates: list[Any] = [payload.get("session_id")]
    candidates.append(result.get("target_session_id"))
    session = result.get("session")
    if isinstance(session, Mapping):
        candidates.append(session.get("session_id"))
    launch = result.get("launch")
    if isinstance(launch, Mapping):
        candidates.append(launch.get("registered_session_id"))
    recipients = result.get("recipients")
    if isinstance(recipients, list):
        for recipient in recipients:
            if isinstance(recipient, Mapping):
                candidates.append(recipient.get("session_id"))
    return _ordered_unique(candidates)


def record_session_action(
    request: FunctionCallRequest,
    function_id: str,
    response: FunctionCallResponse,
    *,
    project: Optional[str] = None,
) -> None:
    """Write one attribution row into each target session's own history."""
    label = action_label(function_id)
    if label is None:
        return
    targets = target_session_ids(function_id, request.payload or {}, response.result)
    if not targets:
        return
    performed_by_session = _text(request.actor.session_id)
    performed_by_actor = _text(request.actor.actor_id)
    if not performed_by_actor:
        # Without an acting actor the row would be backfilled with the
        # TARGET's actor by the session-actor rule, which reads as the
        # session having done this to itself. No row beats a wrong one.
        return
    for target in targets:
        if target == performed_by_session:
            # A session acting on itself is already its own history.
            continue
        _emit(
            target,
            label=label,
            function_id=function_id,
            performed_by_actor=performed_by_actor,
            performed_by_session=performed_by_session,
            succeeded=response.success,
            request_id=request.request_id,
            project=project,
        )


def _emit(
    target_session_id: str,
    *,
    label: str,
    function_id: str,
    performed_by_actor: str,
    performed_by_session: str,
    succeeded: bool,
    request_id: Optional[str],
    project: Optional[str],
) -> None:
    """Emit one row; a write that fails must not fail the action it records."""
    from yoke_core.domain.auth_context import auth_context_from_actor
    from yoke_core.domain.events import emit_event

    try:
        emit_event(
            EVENT_SESSION_ACTION_PERFORMED,
            event_kind="lifecycle",
            event_type="session_action",
            session_id=target_session_id,
            severity="INFO",
            outcome="completed" if succeeded else "failed",
            request_id=request_id,
            project=project or "yoke",
            auth_context=auth_context_from_actor(performed_by_actor),
            context={
                "action": label,
                "function": function_id,
                "performed_by_actor_id": performed_by_actor,
                "performed_by_session_id": performed_by_session,
                "target_session_id": target_session_id,
            },
        )
    except Exception:  # noqa: BLE001 — attribution never fails the action
        return


__all__ = [
    "EVENT_SESSION_ACTION_PERFORMED",
    "SESSION_ACTION_LABELS",
    "action_label",
    "record_session_action",
    "target_session_ids",
]
