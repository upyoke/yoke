"""Handler coverage for the ui_preferences.screen_selection.* surface.

Drives the handlers directly with synthetic envelopes against the
``test_db`` fixture (which repoints the ambient authority, so the
handlers' own ``db_helpers.connect()`` lands in the same database):
actor scoping, per-view independence, and payload validation. Mirrors
test_overview_activation_functions.py's dismiss/restore round trip since
both surfaces share ``actor_ui_preferences``.
"""

from __future__ import annotations

import pytest

from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)
from yoke_core.domain.handlers.screen_selection import (
    handle_screen_selection_list,
    handle_screen_selection_set,
)


def _request(function_id, payload=None, actor_id=None, target=None):
    return FunctionCallRequest(
        function=function_id,
        actor=ActorContext(actor_id=actor_id, session_id=""),
        target=target or TargetRef(kind="global"),
        payload=payload or {},
    )


def _set(payload, actor_id=None):
    return handle_screen_selection_set(
        _request("ui_preferences.screen_selection.set", payload, actor_id),
    )


def _list(actor_id=None):
    outcome = handle_screen_selection_list(
        _request("ui_preferences.screen_selection.list", actor_id=actor_id),
    )
    assert outcome.primary_success, outcome.error
    return outcome.result_payload["views"]


def test_target_invalid_for_both_operations():
    wrong_target = handle_screen_selection_list(
        _request(
            "ui_preferences.screen_selection.list",
            target=TargetRef(kind="item", item_id=1),
        )
    )
    assert wrong_target.error.code == "target_invalid"
    wrong_target = handle_screen_selection_set(
        _request(
            "ui_preferences.screen_selection.set",
            {"view_id": "sessions"},
            actor_id="1",
            target=TargetRef(kind="item", item_id=1),
        )
    )
    assert wrong_target.error.code == "target_invalid"


def test_list_without_actor_reads_back_empty(test_db):
    assert _list() == {}


def test_set_requires_actor(test_db):
    refused = _set({"view_id": "sessions", "selection": "all"})
    assert refused.primary_success is False
    assert refused.error.code == "actor_required"


@pytest.mark.parametrize("view_id", ["", "Sessions", "1sessions", "has space"])
def test_set_refuses_malformed_view_ids(test_db, view_id):
    outcome = _set({"view_id": view_id, "selection": "all"}, actor_id="1")
    assert outcome.primary_success is False
    assert outcome.error.code == "payload_invalid"


@pytest.mark.parametrize("selection", [1, "some", ["1", 2]])
def test_set_refuses_malformed_selections(test_db, selection):
    outcome = _set({"view_id": "sessions", "selection": selection}, actor_id="1")
    assert outcome.primary_success is False
    assert outcome.error.code == "payload_invalid"


def test_set_refuses_malformed_focus(test_db):
    outcome = _set(
        {"view_id": "sessions", "selection": "all", "focus": 3},
        actor_id="1",
    )
    assert outcome.primary_success is False
    assert outcome.error.code == "payload_invalid"


def test_set_then_list_scopes_per_actor_and_stays_independent_per_view(test_db):
    actor = test_db.execute(
        "SELECT id FROM actors WHERE kind = 'human' ORDER BY id LIMIT 1"
    ).fetchone()[0]

    done = _set(
        {"view_id": "sessions", "selection": ["1", "2"], "focus": None},
        actor_id=str(actor),
    )
    assert done.primary_success is True
    assert done.result_payload == {
        "view_id": "sessions",
        "selection": ["1", "2"],
        "focus": None,
    }
    _set({"view_id": "inbox", "selection": "all"}, actor_id=str(actor))

    mine = _list(actor_id=str(actor))
    assert mine == {
        "sessions": {"selection": ["1", "2"], "focus": None},
        "inbox": {"selection": "all", "focus": None},
    }

    # A different actor sees nothing this actor saved.
    assert _list(actor_id="999999") == {}

    # Overwriting a view updates in place rather than duplicating rows.
    _set({"view_id": "sessions", "selection": "all"}, actor_id=str(actor))
    count = test_db.execute(
        "SELECT COUNT(*) FROM actor_ui_preferences WHERE pref_key LIKE "
        "'screen.selection.%%'"
    ).fetchone()[0]
    assert int(count) == 2
    assert _list(actor_id=str(actor))["sessions"] == {"selection": "all", "focus": None}
