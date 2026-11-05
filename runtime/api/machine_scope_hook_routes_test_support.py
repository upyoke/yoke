# ruff: noqa: F401, E402
"""Shared setup for tests in this directory."""

import json

from uuid import uuid4

import pytest

from runtime.api import api_hooks_evaluate_route_actor_test_support as actor_fixtures

from runtime.api.api_hooks_evaluate_route_actor_test_support import (
    _machine_request,
    _stored_session,
)

from yoke_contracts.timestamps import format_instant, utc_now

from yoke_core.domain import db_helpers


def _request(session, machine, workspace, executor="codex", event="PreToolUse"):
    body = _machine_request(session, machine, workspace)
    body.update(executor=executor, event_name=event)
    payload = json.loads(body["stdin"])
    payload.update(
        tool_name="Read",
        tool_input={"file_path": str(workspace / "note")},
        tool_use_id=str(uuid4()),
        transcript_path=str(workspace / "rollout.jsonl"),
    )
    body["stdin"] = json.dumps(payload)
    return body


@pytest.fixture(autouse=True)
def session_schema(hooks_db):
    from yoke_core.domain.schema_init_tables_sessions import create_session_tables

    with db_helpers.connect() as conn:
        create_session_tables(conn)
        conn.commit()


def _batch(*requests):
    return {
        "observations": [
            {
                "observation_id": str(uuid4()),
                "observed_at": format_instant(utc_now()),
                "hook_wait_ms": 3,
                "hook_request": request,
            }
            for request in requests
        ]
    }


def _business_state():
    with db_helpers.connect() as conn:
        return {
            table: [dict(row) for row in conn.execute(f"SELECT * FROM {table}")]
            for table in ("harness_sessions", "work_claims", "session_tool_calls")
        }


def _capability(response):
    assert "machine_scope_hooks" in response.json()["capabilities"]
