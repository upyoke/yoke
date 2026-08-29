"""Request-local context applied while a registered handler executes."""

from __future__ import annotations

from typing import Any, Callable

from yoke_contracts.api.function_call import FunctionCallRequest


def invoke_resolved_handler(
    handler: Callable[[FunctionCallRequest], Any],
    request: FunctionCallRequest,
) -> Any:
    """Invoke a control-plane handler with its resolved actor bound."""
    from yoke_core.domain import project_label_policy
    from yoke_core.domain.events_acting_identity import acting_event_identity

    with (
        project_label_policy.request_overrides(
            request.options.get("label_color_overrides")
        ),
        acting_event_identity(
            session_id=request.actor.session_id,
            actor_id=request.actor.actor_id,
        ),
    ):
        return handler(request)


def invoke_client_local_handler(
    handler: Callable[[FunctionCallRequest], Any],
    request: FunctionCallRequest,
) -> Any:
    """Invoke a machine-local handler without trusting envelope identity."""
    from yoke_core.domain import project_label_policy

    with project_label_policy.request_overrides(
        request.options.get("label_color_overrides")
    ):
        return handler(request)


__all__ = ["invoke_client_local_handler", "invoke_resolved_handler"]
