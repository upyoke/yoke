"""Register organization-admin invite reads and code lifecycle operations."""

from yoke_core.domain.admission_result_redaction import ONE_TIME_SECRET_GUARDRAIL
from yoke_core.domain.handlers import teammate_invites as handlers


def register(registry) -> None:
    for operation, handler, request, response, effects in (
        (
            "create",
            handlers.handle_create,
            handlers.InviteCreateRequest,
            handlers.InviteCreatedResponse,
            ["actors_insert", "actor_org_roles_insert", "teammate_invite_codes_insert"],
        ),
        (
            "list",
            handlers.handle_list,
            handlers.InviteListRequest,
            handlers.InviteListResponse,
            [],
        ),
        (
            "revoke",
            handlers.handle_revoke,
            handlers.InviteIdRequest,
            handlers.InviteResponse,
            ["teammate_invite_codes_update"],
        ),
        (
            "reissue",
            handlers.handle_reissue,
            handlers.InviteIdRequest,
            handlers.InviteCreatedResponse,
            ["teammate_invite_codes_insert", "teammate_invite_codes_update"],
        ),
    ):
        guardrails = ["actor_required", "org_admin"]
        if operation in {"create", "reissue"}:
            guardrails += ["handler_managed_idempotency", ONE_TIME_SECRET_GUARDRAIL]
        registry.register(
            f"teammate_invites.{operation}",
            handler,
            request,
            response,
            stability="stable",
            owner_module=handlers.__name__,
            target_kinds=["global"],
            side_effects=effects,
            emitted_event_names=["YokeFunctionCalled"],
            guardrails=guardrails,
            adapter_status="internal",
            claim_required_kind=None,
            ambient_session_required=False,
            minimum_serving_version="next-release",
        )
