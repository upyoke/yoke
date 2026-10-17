"""Batch eligibility follows the effective tool payload before any state write."""

import json
from uuid import uuid4

import pytest

from runtime.api import test_api_hooks_evaluate_route_actor as actor_fixtures
from runtime.api import test_machine_scope_hook_routes as route_cases
from yoke_core.domain import db_helpers

hooks_db = actor_fixtures.hooks_db
client = actor_fixtures.client
machine_client = actor_fixtures.machine_client
session_schema = route_cases.session_schema

_EXECUTORS = ["claude", "codex", "cursor"]
_EVENTS = ["PreToolUse", "PostToolUse", "PostToolUseFailure"]


@pytest.mark.parametrize(
    "executor,guarded_tool",
    [("claude", "Bash"), ("codex", "Bash"), ("cursor", "Bash"), ("cursor", "Shell")],
)
@pytest.mark.parametrize("event", _EVENTS)
@pytest.mark.parametrize("mixed", [False, True])
def test_effective_guarded_tool_refused_before_any_write(
    machine_client, tmp_path, executor, guarded_tool, event, mixed
):
    client, actor, machine = machine_client
    session, prefix = str(uuid4()), str(uuid4())
    setup = route_cases._request(session, machine, tmp_path, executor, "SessionStart")
    assert (
        client.post("/v1/hooks/evaluate", json=setup).json()["outcome"] == "completed"
    )
    owner = actor_fixtures._stored_session(session)
    assert (owner["project_id"], owner["actor_id"], owner["machine_id"]) == (
        None,
        actor,
        machine,
    )
    assert owner["org_id"] is not None
    body = route_cases._request(session, machine, tmp_path, executor, event)
    body["payload_extra"] = {
        "tool_name": guarded_tool,
        "tool_input": {"command": "printf note"},
    }
    entries = [body]
    if mixed:
        entries.insert(0, route_cases._request(prefix, machine, tmp_path, executor))
    before = route_cases._business_state()
    response = client.post(
        "/v1/hooks/telemetry/batch", json=route_cases._batch(*entries)
    )
    after = route_cases._business_state()
    facts = {
        "response": response.json(),
        "business_changed": after != before,
        "prefix_registered": actor_fixtures._stored_session(prefix) is not None,
        "effective_tools": [
            row["tool_name"]
            for row in after["session_tool_calls"]
            if row["session_id"] == session
        ],
    }
    assert response.status_code == 400, facts
    assert response.json()["error"]["code"] == "HOOK_OBSERVATION_NOT_READ_ONLY"
    assert "Recovery:" in response.json()["error"]["message"]
    route_cases._capability(response)
    assert after == before
    assert actor_fixtures._stored_session(prefix) is None


@pytest.mark.parametrize("executor", _EXECUTORS)
@pytest.mark.parametrize("extra_input", [False, True])
@pytest.mark.parametrize("event", _EVENTS)
def test_effective_read_preserves_real_org_state(
    machine_client, tmp_path, executor, extra_input, event
):
    client, actor, machine = machine_client
    session = str(uuid4())
    body = route_cases._request(session, machine, tmp_path, executor, event)
    expected_path = str(tmp_path / "note")
    if extra_input:
        expected_path = str(tmp_path / "other-note")
        body["payload_extra"] = {"tool_input": {"file_path": expected_path}}
    entries = [body]
    if event != "PreToolUse":
        entries.insert(0, dict(body, event_name="PreToolUse"))
    response = client.post(
        "/v1/hooks/telemetry/batch", json=route_cases._batch(*entries)
    )
    assert response.status_code == 200, response.text
    assert response.json()["accepted"] == len(entries)
    route_cases._capability(response)
    owner = actor_fixtures._stored_session(session)
    assert (owner["project_id"], owner["actor_id"], owner["machine_id"]) == (
        None,
        actor,
        machine,
    )
    assert owner["org_id"] is not None
    with db_helpers.connect() as conn:
        call = conn.execute(
            "SELECT tool_name,command_summary FROM session_tool_calls WHERE session_id=%s",
            (session,),
        ).fetchone()
    assert call["tool_name"] == "Read"
    assert call["command_summary"] == expected_path


@pytest.mark.parametrize("executor", _EXECUTORS)
@pytest.mark.parametrize("event", _EVENTS)
def test_raw_guarded_tool_cannot_be_downgraded_by_extras(
    machine_client, tmp_path, executor, event
):
    client, _, machine = machine_client
    session = str(uuid4())
    body = route_cases._request(session, machine, tmp_path, executor, event)
    payload = json.loads(body["stdin"])
    payload.update(tool_name="Bash", tool_input={"command": "printf note"})
    body["stdin"] = json.dumps(payload)
    body["payload_extra"] = {
        "tool_name": "Read",
        "tool_input": {"file_path": str(tmp_path / "note")},
    }
    before = route_cases._business_state()
    response = client.post("/v1/hooks/telemetry/batch", json=route_cases._batch(body))
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "HOOK_OBSERVATION_NOT_READ_ONLY"
    assert "Recovery:" in response.json()["error"]["message"]
    route_cases._capability(response)
    assert route_cases._business_state() == before
    assert actor_fixtures._stored_session(session) is None
