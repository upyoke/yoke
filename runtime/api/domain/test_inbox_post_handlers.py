"""Typed post endpoints preserve identity, permission and serving contracts."""

from contextlib import contextmanager

import pytest

from runtime.api.domain.decision_request_test_support import decision_request_connection
from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)
from yoke_core.domain import db_helpers
from yoke_core.domain.handlers import inbox_posts, audiences
from yoke_core.domain.handlers.inbox_decision_models import InboxListResponse
from yoke_core.domain.function_authz_product_scopes import PRODUCT_AUTHZ_BY_ID
from yoke_core.domain.actor_permissions import PERM_ITEMS_WRITE


def request(function, actor="2", **payload):
    return FunctionCallRequest(
        function=function,
        target=TargetRef(kind="global"),
        actor=ActorContext(actor_id=actor, session_id=""),
        payload=payload,
    )


@pytest.fixture
def conn(monkeypatch):
    with decision_request_connection() as value:

        @contextmanager
        def connect():
            yield value

        monkeypatch.setattr(db_helpers, "connect", connect)
        yield value


def test_handler_permission_is_independent_of_audience(conn):
    payload = dict(
        project_id=10,
        title="Review",
        body="Details",
        source="Form",
        rules=[{"scope_kind": "actor", "scope_id": 4}],
    )
    denied = inbox_posts.handle_create(request("inbox.posts.create", "4", **payload))
    assert not denied.primary_success and denied.error.code == "permission_denied"
    assert "Recovery" in denied.error.message
    assert conn.execute("SELECT COUNT(*) FROM inbox_posts").fetchone()[0] == 0
    assert PRODUCT_AUTHZ_BY_ID["inbox.posts.create"].permission_key == PERM_ITEMS_WRITE
    allowed = inbox_posts.handle_create(request("inbox.posts.create", **payload))
    assert allowed.primary_success
    assert allowed.result_payload["post"]["created_by_actor_id"] == 2


def test_named_audience_round_trip_and_done_return_same_record(conn):
    created = audiences.handle_create(
        request(
            "audiences.create",
            project_id=10,
            name="Owners",
            rules=[{"scope_kind": "project", "scope_id": 10, "role_name": "owner"}],
        )
    )
    assert created.primary_success
    listed = audiences.handle_list(request("audiences.list", project_id=10))
    assert listed.result_payload == created.result_payload
    post = inbox_posts.handle_create(
        request(
            "inbox.posts.create",
            project_id=10,
            title="Review",
            body="Details",
            source="Form",
            audience_name="Owners",
        )
    )
    post_id = post.result_payload["post"]["id"]
    for already_done in (False, True):
        outcome = inbox_posts.handle_done(request("inbox.posts.done", post_id=post_id))
        assert outcome.primary_success
        assert outcome.result_payload["post"]["already_done"] == already_done
        assert outcome.result_payload["post"]["done_actor_id"] == 2


def test_refusals_and_old_list_response_have_named_recovery(conn):
    outcome = inbox_posts.handle_create(
        request(
            "inbox.posts.create",
            project_id=10,
            title="Review",
            body="",
            source="Form",
            audience_id=999,
        )
    )
    assert not outcome.primary_success and outcome.error.code == "unknown_audience"
    assert "Recovery" in outcome.error.message
    assert not inbox_posts.handle_done(
        request("inbox.posts.done", None, post_id=1)
    ).primary_success
    assert InboxListResponse(needs_decision=[]).posts == []


def test_new_functions_declare_serving_floors():
    from yoke_contracts.function_serving_floors import FUNCTION_MINIMUM_SERVING_VERSIONS

    class Registry:
        def __init__(self):
            self.rows = {}

        def register(self, function, *args, **kwargs):
            self.rows[function] = kwargs

    registry = Registry()
    audiences.register(registry)
    inbox_posts.register(registry)
    assert set(registry.rows) == {
        "audiences.create",
        "audiences.list",
        "inbox.posts.create",
        "inbox.posts.done",
    }
    for function, metadata in registry.rows.items():
        assert metadata["minimum_serving_version"] == "next-release"
        assert FUNCTION_MINIMUM_SERVING_VERSIONS[function] == "next-release"
