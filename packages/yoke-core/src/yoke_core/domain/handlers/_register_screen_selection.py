"""Handler registrations for the ui_preferences.screen_selection.* surface.

Browser-proxied UI surface (``adapter_status="internal"``): the workbench
dispatches these through the local ``yoke ui`` proxy or the hosted
doorman, so no agent CLI adapter exists. The list read degrades to an
empty map without a resolved actor; the set mutation is an ordinary
actor-scoped write and refuses without one — mirroring
``overview.module.dismiss`` / ``.restore`` in ``_register_overview.py``.
"""

from __future__ import annotations

from yoke_core.domain.handlers import screen_selection as _ss


def register(registry) -> None:
    registry.register(
        "ui_preferences.screen_selection.list",
        _ss.handle_screen_selection_list,
        _ss.ScreenSelectionListRequest,
        _ss.ScreenSelectionListResponse,
        stability="stable",
        owner_module="yoke_core.domain.handlers.screen_selection",
        target_kinds=["global"],
        side_effects=[],
        emitted_event_names=["YokeFunctionCalled"],
        guardrails=[],
        adapter_status="internal",
        claim_required_kind=None,
        ambient_session_required=False,
    )
    registry.register(
        "ui_preferences.screen_selection.set",
        _ss.handle_screen_selection_set,
        _ss.ScreenSelectionSetRequest,
        _ss.ScreenSelectionSetResponse,
        stability="stable",
        owner_module="yoke_core.domain.handlers.screen_selection",
        target_kinds=["global"],
        side_effects=["actor_ui_preferences_upsert"],
        emitted_event_names=["YokeFunctionCalled"],
        guardrails=["actor_required"],
        adapter_status="internal",
        claim_required_kind=None,
        ambient_session_required=False,
    )


__all__ = ["register"]
