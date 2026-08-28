"""Registered session keep-alive family: hold and release the lease."""

from __future__ import annotations

from yoke_contracts.session_control.keepalive import (
    SessionKeepaliveHoldRequest,
    SessionKeepaliveReleaseRequest,
    SessionKeepaliveResponse,
)
from yoke_core.domain.handlers import session_keepalive as _keepalive


def register(registry) -> None:
    for operation, handler, request_model in (
        ("hold", _keepalive.handle_session_keepalive_hold, SessionKeepaliveHoldRequest),
        (
            "release",
            _keepalive.handle_session_keepalive_release,
            SessionKeepaliveReleaseRequest,
        ),
    ):
        registry.register(
            f"session_control.keepalive.{operation}",
            handler,
            request_model,
            SessionKeepaliveResponse,
            stability="stable",
            owner_module=_keepalive.__name__,
            target_kinds=["global"],
            side_effects=["harness_sessions_update"],
            emitted_event_names=["YokeFunctionCalled"],
            guardrails=["verified_actor", "handler_enforced_project_authority"],
            adapter_status="live",
            claim_required_kind=None,
            ambient_session_required=False,
        )


__all__ = ["register"]
