"""Client-side read of whether the calling session is a headless command.

The merge boundary runs on the machine holding the git repository and never
opens the control-plane database itself, so it cannot read ``session_launches``
the way a server-side hook does. It asks the registered identity projection
instead, which relays over an https control plane exactly as it dispatches
in-process locally.

An answer the authority does not give — a control plane still serving a build
whose projection carries no such field, or a read that failed outright — is
reported as *not* relay-launched, which leaves the caller's own ``--wait``
exactly as it behaves today. A release reaches every machine before it reaches
every server, so an unknown answer must not change what a fleet mid-rollout
does. The recovery for the case that guesses wrong is already in place either
way: the landing is recorded before any wait begins, so the control-plane
observer still messages the claim holder when it lands.
"""

from __future__ import annotations

from typing import Any, Callable

from yoke_contracts.api.function_call import TargetRef

from yoke_core.api.service_client_structured_api_adapter import call_dispatcher


def calling_session_is_relay_launched(
    *,
    dispatch: Callable[..., Any] = call_dispatcher,
) -> bool:
    """Whether a Yoke relay started the calling session as a headless command."""
    response = dispatch(
        function_id="sessions.identity",
        target=TargetRef(kind="global"),
        payload={},
    )
    if not getattr(response, "success", False):
        return False
    result = getattr(response, "result", None) or {}
    return bool(result.get("relay_launched"))


__all__ = ["calling_session_is_relay_launched"]
