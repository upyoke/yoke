"""Handler registrations for the ui_preferences.search_history.* surface.

Browser-proxied UI surface (``adapter_status="internal"``): the search
dialog dispatches these through the local ``yoke ui`` proxy or the hosted
doorman, so no agent CLI adapter exists. The list read degrades to an
empty list without a resolved actor; the record mutation is an ordinary
actor-scoped write and refuses without one — the same contract as
``ui_preferences.screen_selection.*``.
"""

from __future__ import annotations

from yoke_core.domain.handlers import search_history as _sh


def register(registry) -> None:
    registry.register(
        "ui_preferences.search_history.list",
        _sh.handle_search_history_list,
        _sh.SearchHistoryListRequest,
        _sh.SearchHistoryListResponse,
        stability="stable",
        owner_module="yoke_core.domain.handlers.search_history",
        target_kinds=["global"],
        side_effects=[],
        emitted_event_names=["YokeFunctionCalled"],
        guardrails=[],
        adapter_status="internal",
        claim_required_kind=None,
        ambient_session_required=False,
    )
    registry.register(
        "ui_preferences.search_history.record",
        _sh.handle_search_history_record,
        _sh.SearchHistoryRecordRequest,
        _sh.SearchHistoryRecordResponse,
        stability="stable",
        owner_module="yoke_core.domain.handlers.search_history",
        target_kinds=["global"],
        side_effects=["actor_ui_preferences_upsert"],
        emitted_event_names=["YokeFunctionCalled"],
        guardrails=["actor_required"],
        adapter_status="internal",
        claim_required_kind=None,
        ambient_session_required=False,
    )


__all__ = ["register"]
