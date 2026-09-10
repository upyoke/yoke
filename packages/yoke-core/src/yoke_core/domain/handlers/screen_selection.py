"""Per-screen project-selection preference handlers.

Each workbench screen (Sessions, Inbox, Overview, ...) remembers its own
project-selector value instead of sharing one app-wide selection. The
value lives in the same actor-scoped preference table the Overview
activation dismissals use (``actor_ui_preferences``), keyed
``screen.selection.<view_id>``. ``ui_preferences.screen_selection.list``
returns every remembered selection for the resolved actor in one
dispatch; ``ui_preferences.screen_selection.set`` writes one view's
value. Without a resolved actor the list reads back empty — every
screen falls back to its "all" default — and the set refuses, mirroring
``overview_activation.py``'s dismiss/restore contract.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Union

from pydantic import BaseModel

from yoke_contracts.api.function_call import (
    FunctionCallRequest,
    FunctionError,
    HandlerOutcome,
)

from yoke_core.domain import json_helper

#: ``actor_ui_preferences.pref_key`` prefix for per-view selections.
SCREEN_SELECTION_PREF_PREFIX = "screen.selection."

#: A view id is a NAV entry id (``universe_destinations.js``): a short
#: lowercase slug. Validated by shape here rather than duplicating the
#: NAV roster server-side.
_VIEW_ID_RE = re.compile(r"^[a-z][a-z0-9-]{0,63}$")

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


def _error(
    code: str,
    message: str,
    *,
    jsonpath: Optional[str] = None,
) -> HandlerOutcome:
    return HandlerOutcome(
        primary_success=False,
        error=FunctionError(code=code, message=message, jsonpath=jsonpath),
    )


def _require_global(
    request: FunctionCallRequest,
    function_id: str,
) -> Optional[HandlerOutcome]:
    if request.target.kind != "global":
        return _error(
            "target_invalid",
            f"{function_id} requires target.kind='global'",
            jsonpath="$.target.kind",
        )
    return None


def _actor_id(request: FunctionCallRequest) -> Optional[int]:
    raw = (request.actor.actor_id or "").strip()
    return int(raw) if raw.isdigit() else None


def _valid_selection(selection: Any) -> bool:
    if selection == "all":
        return True
    return isinstance(selection, list) and all(isinstance(v, str) for v in selection)


def handle_screen_selection_list(
    request: FunctionCallRequest,
) -> HandlerOutcome:
    invalid = _require_global(request, "ui_preferences.screen_selection.list")
    if invalid is not None:
        return invalid
    actor_id = _actor_id(request)
    if actor_id is None:
        return HandlerOutcome(result_payload={"views": {}}, primary_success=True)

    from yoke_core.domain import db_helpers

    conn = db_helpers.connect()
    try:
        rows = conn.execute(
            "SELECT pref_key, value FROM actor_ui_preferences "
            "WHERE actor_id = %s AND pref_key LIKE %s",
            (actor_id, SCREEN_SELECTION_PREF_PREFIX + "%"),
        ).fetchall()
    finally:
        conn.close()
    views: Dict[str, Dict[str, Any]] = {}
    for row in rows:
        view_id = str(row[0])[len(SCREEN_SELECTION_PREF_PREFIX) :]
        try:
            parsed = json_helper.loads_text(row[1])
        except ValueError:
            continue
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
    invalid = _require_global(request, "ui_preferences.screen_selection.set")
    if invalid is not None:
        return invalid
    payload = request.payload or {}
    view_id = payload.get("view_id")
    if not isinstance(view_id, str) or not _VIEW_ID_RE.match(view_id):
        return _error(
            "payload_invalid",
            "view_id must be a lowercase view identifier",
            jsonpath="$.payload.view_id",
        )
    selection = payload.get("selection", "all")
    if not _valid_selection(selection):
        return _error(
            "payload_invalid",
            'selection must be "all" or a list of project id strings',
            jsonpath="$.payload.selection",
        )
    focus = payload.get("focus")
    if focus is not None and not isinstance(focus, str):
        return _error(
            "payload_invalid",
            "focus must be a string or null",
            jsonpath="$.payload.focus",
        )
    actor_id = _actor_id(request)
    if actor_id is None:
        return _error(
            "actor_required",
            "ui_preferences.screen_selection.set writes a per-actor "
            "preference and needs a bound actor; this caller has none",
        )

    from yoke_core.domain import db_helpers

    pref_key = SCREEN_SELECTION_PREF_PREFIX + view_id
    value = json_helper.dumps_compact({"selection": selection, "focus": focus})
    conn = db_helpers.connect()
    try:
        conn.execute(
            "INSERT INTO actor_ui_preferences "
            "(actor_id, pref_key, value, updated_at) "
            "VALUES (%s, %s, %s, %s) "
            "ON CONFLICT (actor_id, pref_key) DO UPDATE SET "
            "value = EXCLUDED.value, updated_at = EXCLUDED.updated_at",
            (actor_id, pref_key, value, db_helpers.iso8601_now()),
        )
        conn.commit()
    finally:
        conn.close()
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
