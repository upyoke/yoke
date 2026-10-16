"""Handler registrations for the profile.* surface.

Browser-proxied UI surfaces (``adapter_status="internal"``): the Profile
page dispatches them through the local ``yoke ui`` proxy or the hosted
doorman, which bind the acting actor. ``ambient_session_required=False``
because a browser has no harness session; every handler refuses without a
bound actor, since there is no profile to show or change for nobody.
"""

from __future__ import annotations

from yoke_core.domain.admission_result_redaction import ONE_TIME_SECRET_GUARDRAIL
from yoke_core.domain.handlers import profile as _p
from yoke_core.domain.handlers import profile_tokens as _tokens

_OWNER = "yoke_core.domain.handlers.profile"


def register(registry) -> None:
    registry.register(
        "profile.get",
        _p.handle_profile_get,
        _p.ProfileGetRequest,
        _p.ProfileGetResponse,
        stability="stable",
        owner_module=_OWNER,
        target_kinds=["global"],
        side_effects=[],
        emitted_event_names=["YokeFunctionCalled"],
        guardrails=["actor_required"],
        adapter_status="internal",
        claim_required_kind=None,
        ambient_session_required=False,
    )
    registry.register(
        "profile.token.create",
        _tokens.handle_profile_token_create,
        _tokens.ProfileTokenCreateRequest,
        _tokens.ProfileTokenCreateResponse,
        stability="stable",
        owner_module=_tokens.__name__,
        target_kinds=["global"],
        side_effects=["api_tokens_insert", "api_token_audit_insert"],
        emitted_event_names=["YokeFunctionCalled"],
        guardrails=[
            "actor_required",
            "api_token_actor_bound",
            "handler_managed_idempotency",
            ONE_TIME_SECRET_GUARDRAIL,
        ],
        adapter_status="internal",
        claim_required_kind=None,
        ambient_session_required=False,
    )
    registry.register(
        "profile.token.revoke",
        _tokens.handle_profile_token_revoke,
        _tokens.ProfileTokenRevokeRequest,
        _tokens.ProfileTokenRevokeResponse,
        stability="stable",
        owner_module=_tokens.__name__,
        target_kinds=["global"],
        side_effects=["api_tokens_update", "api_token_audit_insert"],
        emitted_event_names=["YokeFunctionCalled"],
        guardrails=["actor_required", "api_token_actor_bound"],
        adapter_status="internal",
        claim_required_kind=None,
        ambient_session_required=False,
    )
    registry.register(
        "profile.preference.set",
        _p.handle_profile_preference_set,
        _p.ProfilePreferenceSetRequest,
        _p.ProfilePreferenceSetResponse,
        stability="stable",
        owner_module=_OWNER,
        target_kinds=["global"],
        side_effects=[
            "actor_ui_preferences_upsert",
            "actor_ui_preferences_delete",
        ],
        emitted_event_names=["YokeFunctionCalled"],
        guardrails=["actor_required"],
        adapter_status="internal",
        claim_required_kind=None,
        ambient_session_required=False,
    )
    registry.register(
        "profile.onboarding.reset",
        _p.handle_profile_onboarding_reset,
        _p.ProfileOnboardingResetRequest,
        _p.ProfileOnboardingResetResponse,
        stability="stable",
        owner_module=_OWNER,
        target_kinds=["global"],
        side_effects=["actor_ui_preferences_delete"],
        emitted_event_names=["YokeFunctionCalled"],
        guardrails=["actor_required"],
        adapter_status="internal",
        claim_required_kind=None,
        ambient_session_required=False,
    )


__all__ = ["register"]
