"""Handler registration for the identity.* admin family."""
from __future__ import annotations

from yoke_core.domain.handlers import identity_invites as _invites
from yoke_core.domain.handlers import identity_links as _links


def register(registry) -> None:
    """Register the identity admin handlers via the given registry module."""
    registry.register(
        "identity.invite.create", _invites.handle_identity_invite_create,
        _invites.InviteCreateRequest, _invites.InviteCreateResponse,
        stability="stable",
        owner_module="yoke_core.domain.handlers.identity_invites",
        target_kinds=["global"], side_effects=["actor_invites_insert"],
        emitted_event_names=["ActorInviteCreated", "YokeFunctionCalled"],
        guardrails=[], adapter_status="live", claim_required_kind=None,
        ambient_session_required=False,
    )
    registry.register(
        "identity.invite.list", _invites.handle_identity_invite_list,
        _invites.InviteListRequest, _invites.InviteListResponse,
        stability="stable",
        owner_module="yoke_core.domain.handlers.identity_invites",
        target_kinds=["global"], side_effects=[],
        emitted_event_names=["YokeFunctionCalled"],
        guardrails=[], adapter_status="live", claim_required_kind=None,
        ambient_session_required=False,
    )
    registry.register(
        "identity.invite.revoke", _invites.handle_identity_invite_revoke,
        _invites.InviteRevokeRequest, _invites.InviteRevokeResponse,
        stability="stable",
        owner_module="yoke_core.domain.handlers.identity_invites",
        target_kinds=["global"], side_effects=["actor_invites_update"],
        emitted_event_names=["ActorInviteRevoked", "YokeFunctionCalled"],
        guardrails=[], adapter_status="live", claim_required_kind=None,
        ambient_session_required=False,
    )
    registry.register(
        "identity.link.set", _links.handle_identity_link_set,
        _links.LinkSetRequest, _links.LinkSetResponse,
        stability="stable",
        owner_module="yoke_core.domain.handlers.identity_links",
        target_kinds=["global"],
        side_effects=["actor_external_identities_insert", "actor_invites_insert"],
        emitted_event_names=[
            "ExternalIdentityLinked", "ActorInviteCreated", "YokeFunctionCalled",
        ],
        guardrails=[], adapter_status="live", claim_required_kind=None,
        ambient_session_required=False,
    )
    registry.register(
        "identity.autojoin.set", _links.handle_identity_autojoin_set,
        _links.AutojoinSetRequest, _links.AutojoinSetResponse,
        stability="stable",
        owner_module="yoke_core.domain.handlers.identity_links",
        target_kinds=["global"], side_effects=["organizations_update"],
        emitted_event_names=["AutoJoinDomainChanged", "YokeFunctionCalled"],
        guardrails=[], adapter_status="live", claim_required_kind=None,
        ambient_session_required=False,
    )
