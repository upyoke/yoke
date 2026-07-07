"""Token-actor binding for relay-registered sessions.

Sibling of ``test_api_hooks_evaluate_route.py`` (350-line cap) sharing its
DB/client fixtures via import.
"""

from __future__ import annotations

import json

import pytest

from runtime.api.api_items_test_helpers import (
    _client_for_db,
    make_test_db_fixture,
)
from runtime.api.test_api_hooks_evaluate_route import _request_body


@pytest.fixture()
def hooks_db():
    yield from make_test_db_fixture()


@pytest.fixture()
def client(hooks_db):
    with _client_for_db(hooks_db["db_path"]) as authed:
        yield authed


def test_hooks_evaluate_binds_token_actor_at_relayed_registration(
    client, hooks_db,
) -> None:
    """Field-note 12610 (operator decision: BIND): the request carried a
    verified bearer token, so server-side ensure-register must bind that
    token's actor to the ``harness_sessions`` row — mirroring the machine
    actor that locally-evaluated registration binds. NULL-on-relay was the
    recorded asymmetry. Covers the heartbeat-backfill-first ordering too:
    the in-chain heartbeat module may register the row actor-less before
    the ensure-register tail runs, so the binding must heal an existing
    NULL-actor row, not just fresh inserts."""
    from yoke_core.domain import db_helpers

    session_id = "token-actor-bind-session"
    body = _request_body(
        executor="claude",
        stdin=json.dumps({
            "tool_name": "Bash",
            "tool_input": {"command": "true"},
            "cwd": "/client/repo",
            "session_id": session_id,
            "project_id": 1,
        }),
    )
    assert client.post("/v1/hooks/evaluate", json=body).status_code == 200

    conn = db_helpers.connect()
    try:
        row = conn.execute(
            "SELECT actor_id FROM harness_sessions WHERE session_id = %s",
            (session_id,),
        ).fetchone()
        token = conn.execute("SELECT actor_id FROM api_tokens").fetchone()
        assert row is not None, "relayed session must be registered server-side"
        assert row["actor_id"] is not None, (
            "relayed registration must bind the verified token's actor"
        )
        assert int(row["actor_id"]) == int(token["actor_id"]), (
            "the bound actor must be the bearer token's verified actor"
        )
    finally:
        conn.close()
