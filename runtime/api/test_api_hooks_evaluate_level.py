"""Route coverage for wire-carried hook relay execution levels."""

from __future__ import annotations

import json

import pytest

from runtime.api.api_items_test_helpers import _client_for_db, make_test_db_fixture

pytestmark = pytest.mark.usefixtures("bound_project_context")


@pytest.fixture()
def hooks_db():
    yield from make_test_db_fixture()


@pytest.fixture()
def client(hooks_db):
    with _client_for_db(hooks_db["db_path"]) as authed:
        yield authed


def _body(session_id: str, *, event_name: str, execution_level=None) -> dict:
    body = {
        "hook_schema": 1,
        "event_name": event_name,
        "project_id": 1,
        "stdin": json.dumps(
            {
                "tool_name": "Bash",
                "tool_input": {"command": "true"},
                "cwd": "/client/repo",
                "session_id": session_id,
                "project_id": 1,
            }
        ),
        "executor": "claude",
        "deadline_ms": 2500,
    }
    if execution_level is not None:
        body["execution_level"] = execution_level
    return body


def _level_for(session_id: str) -> str:
    from yoke_core.domain import db_helpers

    conn = db_helpers.connect()
    try:
        row = conn.execute(
            "SELECT execution_level FROM harness_sessions WHERE session_id = %s",
            (session_id,),
        ).fetchone()
        assert row is not None
        return row["execution_level"]
    finally:
        conn.close()


def test_hooks_evaluate_wire_level_heals_primary_and_registers_fresh(client) -> None:
    session_id = "wire-level-register-session"

    assert (
        client.post(
            "/v1/hooks/evaluate",
            json=_body(session_id, event_name="PreToolUse"),
        ).status_code
        == 200
    )
    assert _level_for(session_id) == "DARIUS"

    assert (
        client.post(
            "/v1/hooks/evaluate",
            json=_body(
                session_id,
                event_name="UserPromptSubmit",
                execution_level="DARIUS",
            ),
        ).status_code
        == 200
    )
    assert _level_for(session_id) == "DARIUS"

    fresh = "wire-level-fresh-session"
    assert (
        client.post(
            "/v1/hooks/evaluate",
            json=_body(
                fresh,
                event_name="SessionStart",
                execution_level="ALTMAN",
            ),
        ).status_code
        == 200
    )
    assert _level_for(fresh) == "ALTMAN"
