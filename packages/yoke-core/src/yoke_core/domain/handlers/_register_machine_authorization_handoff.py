"""Register the hosted machine-code ingress separately from Inbox actions."""

from yoke_core.domain.handlers import machine_authorization as authorization
from yoke_core.domain.handlers import machine_authorization_handoff as handoff


def register(registry) -> None:
    registry.register(
        "machine_authorization.handoff",
        handoff.handle_handoff,
        handoff.AuthorizationHandoffRequest,
        authorization.AuthorizationResponse,
        stability="stable",
        owner_module=handoff.__name__,
        target_kinds=["global"],
        side_effects=["machine_authorization_insert"],
        guardrails=[
            "service_token_required",
            "org_scope_exact",
            "handler_managed_idempotency",
        ],
        adapter_status="internal",
        claim_required_kind=None,
        ambient_session_required=False,
        minimum_serving_version="next-release",
    )

    registry.register(
        "machine_authorization.handoff_poll",
        handoff.handle_handoff_poll,
        handoff.AuthorizationHandoffPollRequest,
        authorization.AuthorizationResponse,
        stability="stable",
        owner_module=handoff.__name__,
        target_kinds=["global"],
        side_effects=[
            "machine_authorization_consume",
            "machine_register",
            "api_tokens_insert",
        ],
        guardrails=[
            "service_token_required",
            "org_scope_exact",
            "handler_managed_idempotency",
            "one_time_secret_result",
        ],
        adapter_status="internal",
        claim_required_kind=None,
        ambient_session_required=False,
        minimum_serving_version="next-release",
    )
