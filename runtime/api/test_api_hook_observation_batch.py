"""End-to-end API coverage for resident read-only observation batches."""

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


SESSION_ID = "resident-observation-batch-session"
FIRST_OBSERVED_AT = "2026-09-03T20:00:00+00:00"
LAST_OBSERVED_AT = "2026-09-03T20:00:01+00:00"


@pytest.fixture()
def observation_db():
    yield from make_test_db_fixture()


@pytest.fixture()
def client(observation_db):
    with _client_for_db(observation_db["db_path"]) as authed:
        yield authed


@pytest.fixture(autouse=True)
def active_session(observation_db) -> None:
    conn = connect_test_db(observation_db["db_path"])
    try:
        apply_harness_session_columns(conn)
        conn.execute(
            "INSERT INTO harness_sessions "
            "(session_id,executor,provider,workspace,project_id,offered_at,"
            "last_heartbeat) VALUES (%s,'codex','openai','/client/repo',1,%s,%s)",
            (SESSION_ID, "2026-09-01T00:00:00+00:00", "2026-09-01T00:00:00+00:00"),
        )
        conn.commit()
    finally:
        conn.close()


def _hook_request(event_name: str, tool_name: str = "Read") -> dict:
    payload = json.dumps(
        {
            "identity_stamped": True,
            "session_id": SESSION_ID,
            "project_id": 1,
            "tool_name": tool_name,
            "tool_use_id": "resident-read-1",
            "tool_input": {"file_path": "/client/repo/file.py"},
            "tool_response": {"content": "ok"},
            "cwd": "/client/repo",
        }
    )
    return {
        "hook_schema": 1,
        "event_name": event_name,
        "project_id": 1,
        "executor": "codex",
        "deadline_ms": 2500,
        "stdin": attach_evaluator_metadata(
            payload,
            evaluator="resident",
            warm_duration_ms=125,
        ),
    }


def _batch(*, tool_name: str = "Read", project_id: int = 1) -> dict:
    first = _hook_request("PreToolUse", tool_name)
    second = _hook_request("PostToolUse", tool_name)
    first["project_id"] = project_id
    second["project_id"] = project_id
    return {
        "hook_schema": 1,
        "observations": [
            {
                "observation_id": "resident-observation-pre",
                "observed_at": FIRST_OBSERVED_AT,
                "hook_wait_ms": 4,
                "hook_request": first,
            },
            {
                "observation_id": "resident-observation-post",
                "observed_at": LAST_OBSERVED_AT,
                "hook_wait_ms": 6,
                "hook_request": second,
            },
        ],
    }


def _stored_state(observation_db) -> tuple[list, list, dict]:
    conn = connect_test_db(observation_db["db_path"])
    try:
        tool_events = list(
            conn.execute(
                "SELECT event_name,created_at FROM events WHERE session_id=%s "
                "AND event_name IN ('HarnessToolCallStarted','HarnessToolCallCompleted') "
                "ORDER BY created_at",
                (SESSION_ID,),
            )
        )
        dispatches = list(
            conn.execute(
                "SELECT envelope FROM events WHERE session_id=%s "
                "AND event_name='HookDispatchTelemetry' ORDER BY created_at",
                (SESSION_ID,),
            )
        )
        session = conn.execute(
            "SELECT last_heartbeat,last_tool_call_at,tool_call_count "
            "FROM harness_sessions WHERE session_id=%s",
            (SESSION_ID,),
        ).fetchone()
        return tool_events, dispatches, dict(session)
    finally:
        conn.close()


def test_batch_persists_ordered_events_activity_and_evaluator(
    client, observation_db
) -> None:
    response = client.post("/v1/hooks/telemetry/batch", json=_batch())

    assert response.status_code == 200
    assert response.json() == {"hook_schema": 1, "accepted": 2}
    tool_events, dispatches, session = _stored_state(observation_db)
    assert [row["event_name"] for row in tool_events] == [
        "HarnessToolCallStarted",
        "HarnessToolCallCompleted",
    ]
    assert [row["created_at"] for row in tool_events] == [
        FIRST_OBSERVED_AT,
        LAST_OBSERVED_AT,
    ]
    assert len(dispatches) == 2
    contexts = [json.loads(row["envelope"])["context"] for row in dispatches]
    assert [context["evaluator"] for context in contexts] == ["resident", "resident"]
    assert [context["resident_warm_duration_ms"] for context in contexts] == [125, 125]
    assert session == {
        "last_heartbeat": LAST_OBSERVED_AT,
        "last_tool_call_at": LAST_OBSERVED_AT,
        "tool_call_count": 1,
    }


def test_batch_retry_is_idempotent(client, observation_db) -> None:
    body = _batch()
    assert client.post("/v1/hooks/telemetry/batch", json=body).status_code == 200
    retry = client.post("/v1/hooks/telemetry/batch", json=body)

    assert retry.status_code == 200
    tool_events, dispatches, session = _stored_state(observation_db)
    assert len(tool_events) == 2
    assert len(dispatches) == 2
    assert session["tool_call_count"] == 1


def test_batch_rejects_guarded_tools_and_invisible_projects(client) -> None:
    guarded = client.post(
        "/v1/hooks/telemetry/batch",
        json=_batch(tool_name="Bash"),
    )
    assert guarded.status_code == 400
    assert guarded.json()["error"]["code"] == "HOOK_OBSERVATION_NOT_READ_ONLY"

    denied = client.post(
        "/v1/hooks/telemetry/batch",
        json=_batch(project_id=999),
    )
    assert denied.status_code == 403
    assert denied.json()["error"]["code"] == "HOOK_OBSERVATION_PROJECT_DENIED"
