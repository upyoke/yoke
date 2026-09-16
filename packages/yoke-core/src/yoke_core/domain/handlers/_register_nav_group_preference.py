"""Handler registrations for the ui_preferences.nav_group.* surface.

Browser-proxied UI surface (``adapter_status="internal"``): the workbench
dispatches these through the local ``yoke ui`` proxy or the hosted
doorman, so no agent CLI adapter exists. The list read degrades to an
empty map without a resolved actor — every collapsible group then falls
back to its closed default — and the set mutation refuses without one,
mirroring ``ui_preferences.screen_selection.*``.
"""

from __future__ import annotations

from yoke_core.domain.handlers import nav_group_preference as _ng


def register(registry) -> None:
    registry.register(
        "ui_preferences.nav_group.list",
        _ng.handle_nav_group_list,
        _ng.NavGroupListRequest,
        _ng.NavGroupListResponse,
        stability="stable",
        owner_module="yoke_core.domain.handlers.nav_group_preference",
        target_kinds=["global"],
        side_effects=[],
        emitted_event_names=["YokeFunctionCalled"],
        guardrails=[],
        adapter_status="internal",
        claim_required_kind=None,
        ambient_session_required=False,
    )
    registry.register(
        "ui_preferences.nav_group.set",
        _ng.handle_nav_group_set,
        _ng.NavGroupSetRequest,
        _ng.NavGroupSetResponse,
        stability="stable",
        owner_module="yoke_core.domain.handlers.nav_group_preference",
        target_kinds=["global"],
        side_effects=["actor_ui_preferences_upsert"],
        emitted_event_names=["YokeFunctionCalled"],
        guardrails=["actor_required"],
        adapter_status="internal",
        claim_required_kind=None,
        ambient_session_required=False,
    )


__all__ = ["register"]
