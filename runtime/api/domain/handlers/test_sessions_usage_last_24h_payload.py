"""Payload validation for the `sessions.list` 24-hour usage aggregate.

`usage_last_24h` is its own read: it refuses a payload that mixes it with
history, live-roster filters, the singular `project` key, or a non-boolean
value, naming the payload as invalid rather than silently ignoring a key.
"""

from __future__ import annotations

from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)
from yoke_core.domain.handlers.sessions_list import handle_sessions_list


def test_history_and_usage_last_24h_are_mutually_exclusive(test_db):
    request = FunctionCallRequest(
        function="sessions.list",
        actor=ActorContext(actor_id=None, session_id=""),
        target=TargetRef(kind="global"),
        payload={"history": {}, "usage_last_24h": True},
    )
    outcome = handle_sessions_list(request)
    assert not outcome.primary_success
    assert outcome.error.code == "payload_invalid"


def test_usage_last_24h_rejects_singular_project(test_db):
    # Only the plural `projects` scoping key is supported; a caller that
    # sends the singular live-roster `project` key must be told rather
    # than silently ignored.
    request = FunctionCallRequest(
        function="sessions.list",
        actor=ActorContext(actor_id=None, session_id=""),
        target=TargetRef(kind="global"),
        payload={"usage_last_24h": True, "project": "yoke"},
    )
    outcome = handle_sessions_list(request)
    assert not outcome.primary_success
    assert outcome.error.code == "payload_invalid"


def test_usage_last_24h_cannot_combine_with_other_filters(test_db):
    request = FunctionCallRequest(
        function="sessions.list",
        actor=ActorContext(actor_id=None, session_id=""),
        target=TargetRef(kind="global"),
        payload={"usage_last_24h": True, "liveness": "ended"},
    )
    outcome = handle_sessions_list(request)
    assert not outcome.primary_success
    assert outcome.error.code == "payload_invalid"
    assert "usage_last_24h" in outcome.error.message


def test_usage_last_24h_must_be_boolean(test_db):
    request = FunctionCallRequest(
        function="sessions.list",
        actor=ActorContext(actor_id=None, session_id=""),
        target=TargetRef(kind="global"),
        payload={"usage_last_24h": "yes"},
    )
    outcome = handle_sessions_list(request)
    assert not outcome.primary_success
    assert outcome.error.code == "payload_invalid"
