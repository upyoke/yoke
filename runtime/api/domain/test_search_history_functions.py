"""Handler coverage for the ui_preferences.search_history.* surface.

The search dialog's Recent list is this actor's own history, so these
pin what makes it trustworthy: it is per-actor, it is bounded, the same
query searched twice is one entry rather than two, and a caller with no
bound actor reads back empty instead of seeing somebody else's. Drives
the handlers directly with synthetic envelopes against the ``test_db``
fixture, which repoints the ambient authority so the handlers' own
``db_helpers.connect()`` lands in the same database.
"""

from __future__ import annotations

import pytest

from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)
from yoke_core.domain.handlers.search_history import (
    RECENT_QUERY_LIMIT,
    handle_search_history_list,
    handle_search_history_record,
)


def _request(function_id, payload=None, actor_id=None, target=None):
    return FunctionCallRequest(
        function=function_id,
        actor=ActorContext(actor_id=actor_id, session_id=""),
        target=target or TargetRef(kind="global"),
        payload=payload or {},
    )


def _record(query, actor_id=None):
    return handle_search_history_record(
        _request(
            "ui_preferences.search_history.record", {"query": query}, actor_id
        ),
    )


def _list(actor_id=None):
    outcome = handle_search_history_list(
        _request("ui_preferences.search_history.list", actor_id=actor_id),
    )
    assert outcome.primary_success, outcome.error
    return outcome.result_payload["queries"]


def _human_actor(test_db):
    return str(test_db.execute(
        "SELECT id FROM actors WHERE kind = 'human' ORDER BY id LIMIT 1"
    ).fetchone()[0])


def test_target_invalid_for_both_operations():
    item_target = TargetRef(kind="item", item_id=1)
    listed = handle_search_history_list(
        _request("ui_preferences.search_history.list", target=item_target),
    )
    assert listed.error.code == "target_invalid"
    recorded = handle_search_history_record(
        _request(
            "ui_preferences.search_history.record",
            {"query": "release"},
            actor_id="1",
            target=item_target,
        ),
    )
    assert recorded.error.code == "target_invalid"


def test_list_without_actor_reads_back_empty(test_db):
    """The dialog then shows its scope explanation and nothing else —
    never another actor's history, and never an example list."""
    assert _list() == []


def test_record_requires_actor(test_db):
    refused = _record("release")
    assert refused.primary_success is False
    assert refused.error.code == "actor_required"


@pytest.mark.parametrize("query", ["", "   "])
def test_record_refuses_an_empty_query(test_db, query):
    outcome = _record(query, actor_id="1")
    assert outcome.primary_success is False
    assert outcome.error.code == "payload_invalid"


def test_recent_is_newest_first_and_scoped_to_its_actor(test_db):
    actor = _human_actor(test_db)
    for query in ["release-readiness", "YOK-2228"]:
        assert _record(query, actor_id=actor).primary_success is True

    assert _list(actor_id=actor) == ["YOK-2228", "release-readiness"]
    assert _list(actor_id="999999") == []


def test_searching_the_same_thing_twice_moves_it_rather_than_repeating_it(
    test_db,
):
    actor = _human_actor(test_db)
    for query in ["alpha", "beta", "alpha"]:
        _record(query, actor_id=actor)

    assert _list(actor_id=actor) == ["alpha", "beta"]
    # One preference row holds the whole list, so the storage stays one row
    # per actor however much searching they do.
    count = test_db.execute(
        "SELECT COUNT(*) FROM actor_ui_preferences "
        "WHERE pref_key = 'search.recent'"
    ).fetchone()[0]
    assert int(count) == 1


def test_recent_is_bounded_so_it_stays_scannable(test_db):
    actor = _human_actor(test_db)
    queries = [f"query-{index}" for index in range(RECENT_QUERY_LIMIT + 3)]
    for query in queries:
        _record(query, actor_id=actor)

    remembered = _list(actor_id=actor)
    assert len(remembered) == RECENT_QUERY_LIMIT
    assert remembered == list(reversed(queries))[:RECENT_QUERY_LIMIT]
