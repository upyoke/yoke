"""Handler registrations for the overview.* activation-module surface.

All three ids are browser-proxied UI surfaces (``adapter_status=
"internal"``): the workbench Overview dispatches them through the local
``yoke ui`` proxy or the hosted doorman, so no agent CLI adapter exists.
``overview.activation.get`` declares its one sanctioned side effect —
the universe-scoped monotone activation latch; the dismiss/restore pair
are ordinary actor-scoped mutations. ``ambient_session_required=False``
because a browser has no harness session: the local proxy or hosted
doorman binds the acting actor, and the handlers refuse actor-scoped
writes when none is bound.
"""

from __future__ import annotations

from yoke_core.domain.handlers import overview_activation as _oa


def register(registry) -> None:
    registry.register(
        "overview.activation.get", _oa.handle_overview_activation_get,
        _oa.OverviewActivationGetRequest, _oa.OverviewActivationGetResponse,
        stability="stable",
        owner_module="yoke_core.domain.handlers.overview_activation",
        target_kinds=["global"],
        side_effects=["overview_activation_facts_insert"],
        emitted_event_names=["YokeFunctionCalled"],
        guardrails=[],
        adapter_status="internal",
        claim_required_kind=None,
        ambient_session_required=False,
    )
    registry.register(
        "overview.module.dismiss", _oa.handle_overview_module_dismiss,
        _oa.OverviewModuleDismissRequest, _oa.OverviewModuleDismissResponse,
        stability="stable",
        owner_module="yoke_core.domain.handlers.overview_activation",
        target_kinds=["global"],
        side_effects=["actor_ui_preferences_upsert"],
        emitted_event_names=["YokeFunctionCalled"],
        guardrails=["actor_required"],
        adapter_status="internal",
        claim_required_kind=None,
        ambient_session_required=False,
    )
    registry.register(
        "overview.module.restore", _oa.handle_overview_module_restore,
        _oa.OverviewModuleDismissRequest, _oa.OverviewModuleDismissResponse,
        stability="stable",
        owner_module="yoke_core.domain.handlers.overview_activation",
        target_kinds=["global"],
        side_effects=["actor_ui_preferences_delete"],
        emitted_event_names=["YokeFunctionCalled"],
        guardrails=["actor_required"],
        adapter_status="internal",
        claim_required_kind=None,
        ambient_session_required=False,
    )


__all__ = ["register"]
