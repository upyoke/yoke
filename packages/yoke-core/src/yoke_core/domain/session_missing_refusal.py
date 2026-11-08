"""Teach how to obtain a registered session when a write requires one.

Unregistered folders deliberately keep hooks local. A missing session there
is expected; a registered project with broken registration needs diagnosis.
The server cannot infer the client folder from its own machine config.
"""

from __future__ import annotations

from yoke_contracts.field_note_text import DENIAL_FOOTER

from typing import Any


#: How a terminal caller reaches a function that requires a session.
TERMINAL_SUPPORTED_PATH = (
    "Run the same command from a Yoke harness session (claude, codex or cursor) "
    "started in the project folder, or run `yoke sessions begin`."
)


def format_session_missing(
    function_id: str,
    *,
    channels: str,
    contested: Any = None,
    harness_family: str = "",
) -> str:
    """Return the refusal for ``function_id``, addressed to its caller."""
    extra = f" contested_anchors={contested}" if contested else ""
    opening = (
        f"mutating function {function_id!r} could not resolve an ambient "
        f"harness session for this process. Consulted: {channels}.{extra} "
    )
    if not harness_family:
        return opening + (
            f"This process is not running under a harness; this write requires "
            f"a session. {TERMINAL_SUPPORTED_PATH}"
        )
    return opening + (
        f"This write requires a registered session. {TERMINAL_SUPPORTED_PATH} "
        "Outside registered projects, hooks deliberately create no session. "
        "If this session started in a registered project, this is a Yoke "
        f"infrastructure gap: registration or process-anchor resolution failed. {DENIAL_FOOTER} "
        "Operator-debug --session-id is the only ambient-resolution override."
    )


#: Registry guardrail naming functions that act on the caller's own session.
ACTIVE_SESSION_GUARDRAIL = "active_session_required"


def unregistered_session_refusal(entry: Any, request: Any, bound: Any) -> Any:
    """Refuse a session-scoped write whose bound session was never registered.

    A harness in an unregistered folder still exports its own native id, and
    the client sends it, but hooks there deliberately register no session.
    Without this check the handler answers a bare ``not found``.
    """
    if ACTIVE_SESSION_GUARDRAIL not in entry.guardrails or bound.session_registered is not False:
        return None
    from yoke_contracts.api.function_call import FunctionCallResponse, FunctionError

    session_id = request.actor.session_id
    return FunctionCallResponse(
        success=False,
        function=entry.function_id,
        version=entry.version,
        request_id=request.request_id,
        result={},
        warnings=[],
        error=FunctionError(
            code="actor_session_missing",
            message=(
                f"function {entry.function_id!r} needs a registered session, but "
                f"session {session_id!r} is not registered. Outside registered "
                f"projects, hooks deliberately create no session. {TERMINAL_SUPPORTED_PATH}"
            ),
        ),
        event_ids=[],
    )


__all__ = [
    "ACTIVE_SESSION_GUARDRAIL",
    "TERMINAL_SUPPORTED_PATH",
    "format_session_missing",
    "unregistered_session_refusal",
]
