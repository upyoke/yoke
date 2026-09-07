"""The batch endpoint accepts exactly what a live hook may relay.

A Cursor conversation in a plain workspace is recorded as its own session,
so a perfectly canonical session id can equal the conversation alias
beside it. Judging that pair by shape alone refused the batch while the
evaluate route accepted the identical payload, and the resulting HTTP 400
sat at the head of an ordered queue.
"""

from __future__ import annotations

import json

import pytest

from runtime.api.api_items_test_helpers import (
    _client_for_db,
    make_test_db_fixture,
)
from runtime.api.fixtures.file_test_db import connect_test_db
from yoke_contracts.hook_evaluator_protocol import attach_evaluator_metadata
from yoke_core.domain.schema_harness_session_columns import (
    apply_harness_session_columns,
)
from yoke_core.domain.schema_init_tables_sessions import create_session_tables


# The self-mapped Cursor shape: the conversation id is the session id.
SELF_MAPPED_SESSION_ID = "0199e3aa-71c4-7b52-9c30-2b0c5f5f61aa"
OBSERVED_AT = "2026-09-05T10:33:00+00:00"


@pytest.fixture()
def identity_db():
    yield from make_test_db_fixture()


@pytest.fixture()
def client(identity_db):
    with _client_for_db(identity_db["db_path"]) as authed:
        yield authed


@pytest.fixture(autouse=True)
def session_row(identity_db) -> None:
    conn = connect_test_db(identity_db["db_path"])
    try:
        apply_harness_session_columns(conn)
        create_session_tables(conn)
        conn.execute(
            "INSERT INTO harness_sessions "
            "(session_id,executor,provider,workspace,project_id,offered_at,"
            "last_heartbeat) VALUES (%s,'cursor','anthropic','/client/repo',1,%s,%s)",
            (SELF_MAPPED_SESSION_ID, OBSERVED_AT, OBSERVED_AT),
        )
        conn.commit()
    finally:
        conn.close()


def _payload(**overrides) -> dict:
    payload = {
        "identity_stamped": True,
        "session_id": SELF_MAPPED_SESSION_ID,
        # Cursor carries the conversation beside the session, and here the
        # two are legitimately the same string.
        "conversation_id": SELF_MAPPED_SESSION_ID,
        "project_id": 1,
        "tool_name": "Read",
        "tool_use_id": "cursor-read-1",
        "tool_input": {"file_path": "/client/repo/file.py"},
        "tool_response": {"content": "ok"},
        "cwd": "/client/repo",
    }
    payload.update(overrides)
    return payload


def _batch(payload: dict) -> dict:
    hook_request = {
        "hook_schema": 1,
        "event_name": "PreToolUse",
        "project_id": 1,
        "executor": "cursor",
        "deadline_ms": 2500,
        "stdin": attach_evaluator_metadata(
            json.dumps(payload),
            evaluator="resident",
            warm_duration_ms=125,
        ),
    }
    return {
        "hook_schema": 1,
        "observations": [
            {
                "observation_id": "cursor-observation-1",
                "observed_at": OBSERVED_AT,
                "hook_wait_ms": 4,
                "hook_request": hook_request,
            }
        ],
    }


def _evaluate_body(payload: dict) -> dict:
    return {
        "hook_schema": 1,
        "event_name": "PreToolUse",
        "project_id": 1,
        "executor": "cursor",
        "deadline_ms": 2500,
        "stdin": json.dumps(payload),
    }


def test_self_mapped_cursor_session_is_accepted_by_both_routes(client) -> None:
    evaluated = client.post("/v1/hooks/evaluate", json=_evaluate_body(_payload()))
    assert evaluated.status_code == 200, evaluated.text
    assert evaluated.json()["outcome"] == "completed"

    batched = client.post("/v1/hooks/telemetry/batch", json=_batch(_payload()))
    assert batched.status_code == 200, batched.text
    assert batched.json()["accepted"] == 1


def test_unstamped_conversation_alias_is_refused_by_both_routes(client) -> None:
    payload = _payload(identity_stamped=False)

    evaluated = client.post("/v1/hooks/evaluate", json=_evaluate_body(payload))
    assert evaluated.json()["outcome"] == "denied"
    assert "conversation-shaped" in evaluated.json()["stdout"]

    batched = client.post("/v1/hooks/telemetry/batch", json=_batch(payload))
    assert batched.status_code == 400
    assert batched.json()["error"]["code"] == "HOOK_OBSERVATION_IDENTITY_REQUIRED"


def test_blank_session_id_is_refused_by_both_routes(client) -> None:
    payload = _payload(session_id="   ")

    evaluated = client.post("/v1/hooks/evaluate", json=_evaluate_body(payload))
    assert evaluated.json()["outcome"] == "denied"

    batched = client.post("/v1/hooks/telemetry/batch", json=_batch(payload))
    assert batched.status_code == 400
    assert batched.json()["error"]["code"] == "HOOK_OBSERVATION_SESSION_INVALID"


def test_batch_refuses_a_session_owned_by_another_actor(client, identity_db) -> None:
    conn = connect_test_db(identity_db["db_path"])
    try:
        conn.execute(
            "UPDATE harness_sessions SET actor_id = %s WHERE session_id = %s",
            (4242, SELF_MAPPED_SESSION_ID),
        )
        conn.commit()
    finally:
        conn.close()

    denied = client.post("/v1/hooks/telemetry/batch", json=_batch(_payload()))

    assert denied.status_code == 403, denied.text
    assert denied.json()["error"]["code"] == "HOOK_OBSERVATION_SESSION_DENIED"


def test_batch_accepts_a_session_id_with_no_row_yet(client) -> None:
    """The observation that registers a session must not be refused first."""
    payload = _payload(session_id="0199e3aa-71c4-7b52-9c30-unregistered")

    accepted = client.post("/v1/hooks/telemetry/batch", json=_batch(payload))

    assert accepted.status_code == 200, accepted.text


def test_shape_alone_cannot_tell_this_session_from_a_raw_alias() -> None:
    """Why the stamped path no longer consults the alias-shape test.

    This payload carries a canonical session id, and the shape test still
    reports it conversation-shaped — which is exactly the refusal the
    batch route used to render as HTTP 400.
    """
    from yoke_contracts.payload_session_fold import (
        is_conversation_shaped_session_id,
    )

    assert is_conversation_shaped_session_id(
        _payload(), session_id=SELF_MAPPED_SESSION_ID
    )
