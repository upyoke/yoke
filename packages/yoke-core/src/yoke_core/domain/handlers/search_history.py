"""Per-actor recent-search history for the workbench search dialog.

The dialog opens on an empty state, and the useful thing to put there is
what this operator searched for before — not an example list, which
asserts a history the product never recorded. One row in
``actor_ui_preferences`` holds it, keyed ``search.recent``, the same
actor-scoped storage the screen selections and nav groups already use:
``ui_preferences.search_history.list`` reads it back newest-first, and
``ui_preferences.search_history.record`` pushes one query onto it.

Without a resolved actor the list reads back empty — the dialog shows
its scope explanation and nothing else — and the record refuses by name,
mirroring ``screen_selection.py``'s contract.
"""

from __future__ import annotations

from typing import Any, List

from pydantic import BaseModel

from yoke_contracts.api.function_call import FunctionCallRequest, HandlerOutcome

from yoke_core.domain.handlers import actor_ui_preference_store as _store

#: ``actor_ui_preferences.pref_key`` namespace and the one key under it.
SEARCH_PREF_PREFIX = "search."
RECENT_PREF_SEGMENT = "recent"

#: How many past queries the dialog offers. A recent list is a shortcut,
#: not an archive: past a handful it stops being scannable and starts
#: being a second thing to search.
RECENT_QUERY_LIMIT = 5
#: Long enough for a full session id; anything past that is a paste, not
#: a query worth offering back.
MAX_QUERY_LENGTH = 120

_LIST_ID = "ui_preferences.search_history.list"
_RECORD_ID = "ui_preferences.search_history.record"


class SearchHistoryListRequest(BaseModel):
    pass


class SearchHistoryListResponse(BaseModel):
    queries: List[str]


class SearchHistoryRecordRequest(BaseModel):
    query: str


class SearchHistoryRecordResponse(BaseModel):
    queries: List[str]


def _stored_queries(resolved_actor_id: int) -> List[str]:
    stored = _store.read_prefixed(resolved_actor_id, SEARCH_PREF_PREFIX)
    queries = stored.get(RECENT_PREF_SEGMENT)
    if not isinstance(queries, list):
        return []
    return [q for q in queries if isinstance(q, str) and q][:RECENT_QUERY_LIMIT]


def handle_search_history_list(request: FunctionCallRequest) -> HandlerOutcome:
    invalid = _store.require_global(request, _LIST_ID)
    if invalid is not None:
        return invalid
    actor_id = _store.actor_id(request)
    if actor_id is None:
        return HandlerOutcome(result_payload={"queries": []}, primary_success=True)
    return HandlerOutcome(
        result_payload={"queries": _stored_queries(actor_id)},
        primary_success=True,
    )


def handle_search_history_record(request: FunctionCallRequest) -> HandlerOutcome:
    invalid = _store.require_global(request, _RECORD_ID)
    if invalid is not None:
        return invalid
    payload: Any = request.payload or {}
    query = payload.get("query")
    if not isinstance(query, str) or not query.strip():
        return _store.error(
            "payload_invalid",
            "query must be the non-empty text that was searched for",
            jsonpath="$.payload.query",
        )
    query = query.strip()[:MAX_QUERY_LENGTH]
    actor_id = _store.actor_id(request)
    if actor_id is None:
        return _store.actor_required(_RECORD_ID)
    # Re-searching something already remembered moves it to the front
    # rather than filling the list with one query repeated.
    remaining = [q for q in _stored_queries(actor_id) if q != query]
    queries = [query, *remaining][:RECENT_QUERY_LIMIT]
    _store.upsert(actor_id, SEARCH_PREF_PREFIX + RECENT_PREF_SEGMENT, queries)
    return HandlerOutcome(result_payload={"queries": queries}, primary_success=True)


__all__ = [
    "MAX_QUERY_LENGTH",
    "RECENT_PREF_SEGMENT",
    "RECENT_QUERY_LIMIT",
    "SEARCH_PREF_PREFIX",
    "SearchHistoryListRequest",
    "SearchHistoryListResponse",
    "SearchHistoryRecordRequest",
    "SearchHistoryRecordResponse",
    "handle_search_history_list",
    "handle_search_history_record",
]
