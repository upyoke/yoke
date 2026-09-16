"""Per-actor open/closed state for a collapsible workbench nav group.

The sidebar's Diagnostics group is a drawer, and which way an operator
left it is their choice rather than the app's. Absence is the only thing
that means "closed": a group nobody has touched starts closed, and one
they opened stays open across reloads, reconnects and machines, because
the answer lives with the actor rather than in this tab's memory.

Storage is the shared actor preference table, keyed ``nav.group.<id>``.
"""

from __future__ import annotations

from typing import Dict, Optional

from pydantic import BaseModel

from yoke_contracts.api.function_call import FunctionCallRequest, HandlerOutcome

from yoke_core.domain.handlers import actor_ui_preference_store as _store

#: ``actor_ui_preferences.pref_key`` prefix for nav group open state.
NAV_GROUP_PREF_PREFIX = "nav.group."

_LIST_ID = "ui_preferences.nav_group.list"
_SET_ID = "ui_preferences.nav_group.set"


class NavGroupListRequest(BaseModel):
    pass


class NavGroupListResponse(BaseModel):
    groups: Dict[str, bool]


class NavGroupSetRequest(BaseModel):
    group_id: str
    open: bool


class NavGroupSetResponse(BaseModel):
    group_id: str
    open: bool


def handle_nav_group_list(request: FunctionCallRequest) -> HandlerOutcome:
    invalid = _store.require_global(request, _LIST_ID)
    if invalid is not None:
        return invalid
    actor_id = _store.actor_id(request)
    if actor_id is None:
        return HandlerOutcome(result_payload={"groups": {}}, primary_success=True)
    stored = _store.read_prefixed(actor_id, NAV_GROUP_PREF_PREFIX)
    groups = {
        group_id: bool(value.get("open"))
        for group_id, value in stored.items()
        if isinstance(value, dict) and isinstance(value.get("open"), bool)
    }
    return HandlerOutcome(result_payload={"groups": groups}, primary_success=True)


def handle_nav_group_set(request: FunctionCallRequest) -> HandlerOutcome:
    invalid = _store.require_global(request, _SET_ID)
    if invalid is not None:
        return invalid
    payload = request.payload or {}
    group_id = payload.get("group_id")
    if not isinstance(group_id, str) or not _store.KEY_SEGMENT_RE.match(group_id):
        return _store.error(
            "payload_invalid",
            "group_id must be a lowercase navigation group identifier",
            jsonpath="$.payload.group_id",
        )
    is_open = payload.get("open")
    if not isinstance(is_open, bool):
        return _store.error(
            "payload_invalid",
            "open must be true or false",
            jsonpath="$.payload.open",
        )
    actor_id: Optional[int] = _store.actor_id(request)
    if actor_id is None:
        return _store.actor_required(_SET_ID)
    _store.upsert(
        actor_id, NAV_GROUP_PREF_PREFIX + group_id, {"open": is_open}
    )
    return HandlerOutcome(
        result_payload={"group_id": group_id, "open": is_open},
        primary_success=True,
    )


__all__ = [
    "NAV_GROUP_PREF_PREFIX",
    "NavGroupListRequest",
    "NavGroupListResponse",
    "NavGroupSetRequest",
    "NavGroupSetResponse",
    "handle_nav_group_list",
    "handle_nav_group_set",
]
