"""Route coverage for wire-carried hook relay execution lanes."""

from __future__ import annotations

import json

import pytest

from runtime.api.api_items_test_helpers import _client_for_db, make_test_db_fixture


@pytest.fixture()
def hooks_db():
    yield from make_test_db_fixture()


@pytest.fixture()
def client(hooks_db):
    with _client_for_db(hooks_db["db_path"]) as authed:
        yield authed


def _body(session_id: str, *, event_name: str, execution_lane=None) -> dict:
    body = {
        "hook_schema": 1,
        "event_name": event_name,
        "project_id": 1,
        "stdin": json.dumps({
            "tool_name": "Bash",
            "tool_input": {"command": "true"},
            "cwd": "/client/repo",
            "session_id": session_id,
            "project_id": 1,
        }),
        "executor": "claude",
        "deadline_ms": 2500,
    }
    if execution_lane is not None:
        body["execution_lane"] = execution_lane
    return body


def _lane_for(session_id: str) -> str:
    from yoke_core.domain import db_helpers

    conn = db_helpers.connect()
    try:
        row = conn.execute(
            "SELECT execution_lane FROM harness_sessions WHERE session_id = %s",
            (session_id,),
        ).fetchone()
        assert row is not None
        return row["execution_lane"]
    finally:
        conn.close()


def test_hooks_evaluate_wire_lane_heals_primary_and_registers_fresh(client) -> None:
    session_id = "wire-lane-register-session"

    assert client.post(
        "/v1/hooks/evaluate",
        json=_body(session_id, event_name="PreToolUse"),
    ).status_code == 200
    assert _lane_for(session_id) == "DARIUS"

    assert client.post(
        "/v1/hooks/evaluate",
        json=_body(
            session_id,
            event_name="UserPromptSubmit",
            execution_lane="DARIUS",
        ),
    ).status_code == 200
    assert _lane_for(session_id) == "DARIUS"

    fresh = "wire-lane-fresh-session"
    assert client.post(
        "/v1/hooks/evaluate",
        json=_body(
            fresh,
            event_name="SessionStart",
            execution_lane="ALTMAN",
        ),
    ).status_code == 200
    assert _lane_for(fresh) == "ALTMAN"
