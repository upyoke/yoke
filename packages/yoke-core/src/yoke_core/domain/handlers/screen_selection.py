"""Per-screen project-selection preference handlers.

Each workbench screen (Sessions, Inbox, Frontier, ...) remembers its own
project-selector value instead of sharing one app-wide selection. The
value lives in the same actor-scoped preference table the activation
dismissals use (``actor_ui_preferences``), keyed
``screen.selection.<view_id>``. ``ui_preferences.screen_selection.list``
returns every remembered selection for the resolved actor in one
dispatch; ``ui_preferences.screen_selection.set`` writes one view's
value. Without a resolved actor the list reads back empty — every
screen falls back to its "all" default — and the set refuses, mirroring
``overview_activation.py``'s dismiss/restore contract.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Union

from pydantic import BaseModel

from yoke_contracts.api.function_call import FunctionCallRequest, HandlerOutcome

from yoke_core.domain.handlers import actor_ui_preference_store as _store

#: ``actor_ui_preferences.pref_key`` prefix for per-view selections.
SCREEN_SELECTION_PREF_PREFIX = "screen.selection."

_LIST_ID = "ui_preferences.screen_selection.list"
_SET_ID = "ui_preferences.screen_selection.set"

Selection = Union[str, List[str]]


class ScreenSelectionListRequest(BaseModel):
    pass


class ScreenSelectionListResponse(BaseModel):
    views: Dict[str, Dict[str, Any]]


class ScreenSelectionSetRequest(BaseModel):
    view_id: str
    selection: Selection = "all"
    focus: Optional[str] = None


class ScreenSelectionSetResponse(BaseModel):
    view_id: str
    selection: Selection
    focus: Optional[str] = None


def _valid_selection(selection: Any) -> bool:
    if selection == "all":
        return True
    return isinstance(selection, list) and all(isinstance(v, str) for v in selection)


def handle_screen_selection_list(
    request: FunctionCallRequest,
) -> HandlerOutcome:
    invalid = _store.require_global(request, _LIST_ID)
    if invalid is not None:
        return invalid
    actor_id = _store.actor_id(request)
    if actor_id is None:
        return HandlerOutcome(result_payload={"views": {}}, primary_success=True)
    stored = _store.read_prefixed(actor_id, SCREEN_SELECTION_PREF_PREFIX)
    views: Dict[str, Dict[str, Any]] = {}
    for view_id, parsed in stored.items():
        if not isinstance(parsed, dict) or not _valid_selection(
            parsed.get("selection")
        ):
            continue
        focus = parsed.get("focus")
        views[view_id] = {
            "selection": parsed["selection"],
            "focus": focus if isinstance(focus, str) else None,
        }
    return HandlerOutcome(result_payload={"views": views}, primary_success=True)


def handle_screen_selection_set(
    request: FunctionCallRequest,
) -> HandlerOutcome:
    invalid = _store.require_global(request, _SET_ID)
    if invalid is not None:
        return invalid
    payload = request.payload or {}
    view_id = payload.get("view_id")
    if not isinstance(view_id, str) or not _store.KEY_SEGMENT_RE.match(view_id):
        return _store.error(
            "payload_invalid",
            "view_id must be a lowercase view identifier",
            jsonpath="$.payload.view_id",
        )
    selection = payload.get("selection", "all")
    if not _valid_selection(selection):
        return _store.error(
            "payload_invalid",
            'selection must be "all" or a list of project id strings',
            jsonpath="$.payload.selection",
        )
    focus = payload.get("focus")
    if focus is not None and not isinstance(focus, str):
        return _store.error(
            "payload_invalid",
            "focus must be a string or null",
            jsonpath="$.payload.focus",
        )
    actor_id = _store.actor_id(request)
    if actor_id is None:
        return _store.actor_required(_SET_ID)
    _store.upsert(
        actor_id,
        SCREEN_SELECTION_PREF_PREFIX + view_id,
        {"selection": selection, "focus": focus},
    )
    return HandlerOutcome(
        result_payload={"view_id": view_id, "selection": selection, "focus": focus},
        primary_success=True,
    )


__all__ = [
    "SCREEN_SELECTION_PREF_PREFIX",
    "ScreenSelectionListRequest",
    "ScreenSelectionListResponse",
    "ScreenSelectionSetRequest",
    "ScreenSelectionSetResponse",
    "handle_screen_selection_list",
    "handle_screen_selection_set",
]
