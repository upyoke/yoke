"""Authenticated hook routes preserve exclusive scope before any business write."""

import json
from uuid import uuid4

import pytest

from runtime.api import test_api_hooks_evaluate_route_actor as actor_fixtures
from runtime.api.test_api_hooks_evaluate_route_actor import (
    _machine_request,
    _stored_session,
)
from yoke_contracts.timestamps import format_instant, utc_now
from yoke_core.domain import db_helpers

hooks_db = actor_fixtures.hooks_db
client = actor_fixtures.client
machine_client = actor_fixtures.machine_client


@pytest.fixture(autouse=True)
def session_schema(hooks_db):
    from yoke_core.domain.schema_init_tables_sessions import create_session_tables

    with db_helpers.connect() as conn:
        create_session_tables(conn)
        conn.commit()


def _request(session, machine, workspace, executor="codex", event="PreToolUse"):
    body = _machine_request(session, machine, workspace)
    body.update(executor=executor, event_name=event)
    payload = json.loads(body["stdin"])
    payload.update(
        tool_name="Read",
        tool_input={"file_path": str(workspace / "note")},
        tool_use_id=str(uuid4()),
    )
    body["stdin"] = json.dumps(payload)
    return body


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


@pytest.mark.parametrize("executor", ["claude", "codex", "cursor"])
@pytest.mark.parametrize("event", ["SessionStart", "UserPromptSubmit", "PreToolUse"])
def test_single_route_machine_scope_accepted(machine_client, tmp_path, executor, event):
    client, actor, machine = machine_client
    session = str(uuid4())
    response = client.post(
        "/v1/hooks/evaluate", json=_request(session, machine, tmp_path, executor, event)
    )
    assert response.status_code == 200 and response.json()["outcome"] == "completed"
    _capability(response)
    row = _stored_session(session)
    assert row["project_id"] is None and row["org_id"] is not None
    assert (row["actor_id"], row["machine_id"], row["workspace"]) == (
        actor,
        machine,
        str(tmp_path),
    )


@pytest.mark.parametrize("executor", ["claude", "codex", "cursor"])
def test_batch_machine_scope_accepted(machine_client, tmp_path, executor):
    client, actor, machine = machine_client
    session = str(uuid4())
    body = _request(session, machine, tmp_path, executor)
    response = client.post("/v1/hooks/telemetry/batch", json=_batch(body))
    assert response.status_code == 200, response.text
    assert response.json()["accepted"] == 1
    _capability(response)
    row = _stored_session(session)
    assert (row["project_id"], row["actor_id"], row["machine_id"]) == (
        None,
        actor,
        machine,
    )
    assert row["org_id"] is not None


@pytest.mark.parametrize("route", ["/v1/hooks/evaluate", "/v1/hooks/telemetry/batch"])
@pytest.mark.parametrize(
    "spoof", ["actor", "machine", "session_machine", "org", "unbound"]
)
def test_spoofed_scope_refused_no_write(machine_client, tmp_path, route, spoof):
    from yoke_core.domain import actors, api_tokens

    client, actor, machine = machine_client
    session = str(uuid4())
    body = _request(session, machine, tmp_path)
    assert client.post("/v1/hooks/evaluate", json=body).json()["outcome"] == "completed"
    with db_helpers.connect() as conn:
        if spoof == "actor":
            other = actors.seed_system_actor(conn, "foreign-owner")
            conn.execute(
                "UPDATE harness_sessions SET actor_id=%s WHERE session_id=%s",
                (other, session),
            )
        elif spoof == "session_machine":
            conn.execute(
                "UPDATE harness_sessions SET machine_id=%s WHERE session_id=%s",
                (str(uuid4()), session),
            )
        elif spoof == "org":
            conn.execute(
                "UPDATE harness_sessions SET org_id=org_id+100 WHERE session_id=%s",
                (session,),
            )
        elif spoof == "unbound":
            token = api_tokens.mint_token(conn, actor_id=actor, name="unbound")
            client.headers["authorization"] = f"Bearer {token.raw_token}"
        else:
            body["machine_id"] = str(uuid4())
        conn.commit()
    before = _business_state()
    response = client.post(
        route, json=_batch(body) if route.endswith("batch") else body
    )
    data = response.json()
    reason = data["error"]["message"] if "error" in data else data["stdout"]
    assert "Recovery:" in reason, data
    assert (
        response.status_code == 403
        if route.endswith("batch")
        else data["outcome"] == "denied"
    )
    assert _business_state() == before
    _capability(response)


def test_batch_mixed_refused_whole_no_write(machine_client, tmp_path):
    from yoke_core.domain import actors

    client, _, machine = machine_client
    foreign, fresh = str(uuid4()), str(uuid4())
    assert (
        client.post(
            "/v1/hooks/evaluate", json=_request(foreign, machine, tmp_path)
        ).json()["outcome"]
        == "completed"
    )
    with db_helpers.connect() as conn:
        other = actors.seed_system_actor(conn, "foreign-owner")
        conn.execute(
            "UPDATE harness_sessions SET actor_id=%s WHERE session_id=%s",
            (other, foreign),
        )
        conn.commit()
    before = _business_state()
    response = client.post(
        "/v1/hooks/telemetry/batch",
        json=_batch(
            _request(fresh, machine, tmp_path), _request(foreign, machine, tmp_path)
        ),
    )
    assert response.status_code == 403
    assert "Recovery:" in response.json()["error"]["message"]
    assert _business_state() == before and _stored_session(fresh) is None
    _capability(response)


@pytest.mark.parametrize("route", ["/v1/hooks/evaluate", "/v1/hooks/telemetry/batch"])
def test_missing_auth_refused(machine_client, tmp_path, route):
    client, _, machine = machine_client
    client.headers.pop("authorization")
    before = _business_state()
    body = _request(str(uuid4()), machine, tmp_path)
    response = client.post(
        route, json=_batch(body) if route.endswith("batch") else body
    )
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "authentication_required"
    assert _business_state() == before


@pytest.mark.parametrize("route", ["/v1/hooks/evaluate", "/v1/hooks/telemetry/batch"])
def test_authority_unavailable_503(machine_client, tmp_path, monkeypatch, route):
    from yoke_core.domain import session_scope_identity

    client, _, machine = machine_client
    before = _business_state()

    def unavailable(*args):
        raise OSError("authority unavailable")

    monkeypatch.setattr(
        session_scope_identity, "session_ownership_refusal", unavailable
    )
    body = _request(str(uuid4()), machine, tmp_path)
    response = client.post(
        route, json=_batch(body) if route.endswith("batch") else body
    )
    assert response.status_code == 503
    assert "AUTH_UNAVAILABLE" in response.text and "Recovery:" in response.text
    assert _business_state() == before
    _capability(response)


@pytest.mark.parametrize("batched", [False, True])
def test_project_scope_membership_unchanged(machine_client, tmp_path, batched):
    client, actor, machine = machine_client
    session = str(uuid4())
    body = _request(session, machine, tmp_path)
    body["project_id"] = 1
    assert client.post("/v1/hooks/evaluate", json=body).json()["outcome"] == "completed"
    body["project_id"] = None
    with db_helpers.connect() as conn:
        conn.execute("DELETE FROM actor_project_roles WHERE actor_id=%s", (actor,))
        conn.execute("DELETE FROM actor_org_roles WHERE actor_id=%s", (actor,))
        conn.commit()
    before = _business_state()
    response = client.post(
        "/v1/hooks/telemetry/batch" if batched else "/v1/hooks/evaluate",
        json=_batch(body) if batched else body,
    )
    assert "PROJECT_DENIED" in response.text and "Recovery:" in response.text
    assert _business_state() == before
    _capability(response)


def test_batch_effective_identity_overrides_untrusted_extras(machine_client, tmp_path):
    client, actor, machine = machine_client
    session, forged = str(uuid4()), str(uuid4())
    body = _request(session, machine, tmp_path)
    assert client.post("/v1/hooks/evaluate", json=body).json()["outcome"] == "completed"
    body.update(
        project_id=1,
        payload_extra={
            "session_id": forged,
            "project_id": 1,
            "actor_id": actor + 100,
            "org_id": 999,
            "machine_id": "forged",
        },
    )
    response = client.post("/v1/hooks/telemetry/batch", json=_batch(body))
    assert response.status_code == 200, response.text
    row = _stored_session(session)
    assert (row["project_id"], row["actor_id"], row["machine_id"]) == (
        None,
        actor,
        machine,
    )
    assert row["org_id"] != 999 and _stored_session(forged) is None


def test_guard_denial_advertises_machine_scope_capability(machine_client, tmp_path):
    from runtime.api.test_api_hooks_evaluate_server_guardrails import (
        _seed_recent_claim_denial_state,
    )

    client, _, machine = machine_client
    session = str(uuid4())
    _seed_recent_claim_denial_state(
        session_id=session, holder_session_id="other-holder", item_id=42
    )
    body = _request(session, machine, tmp_path, "claude")
    body["project_id"] = 1
    payload = json.loads(body["stdin"])
    payload.update(
        tool_name="Bash",
        tool_input={
            "command": "python3 -m yoke_core.cli.db_router items update YOK-42 status implementing"
        },
    )
    body["stdin"] = json.dumps(payload)
    response = client.post("/v1/hooks/evaluate", json=body)
    assert response.json()["outcome"] == "denied"
    assert "claim-boundary bypass" in response.json()["stdout"]
    _capability(response)


@pytest.mark.parametrize(
    "batched,invalid",
    [(False, "schema"), (False, "stamp"), (True, "schema"), (True, "stamp")],
)
def test_protocol_refusals_advertise_capability(
    machine_client, tmp_path, batched, invalid
):
    client, _, machine = machine_client
    body = _request(str(uuid4()), machine, tmp_path)
    if invalid == "schema":
        body["hook_schema"] = 99
    else:
        payload = json.loads(body["stdin"])
        payload["session_id"] = ""
        body["stdin"] = json.dumps(payload)
    before = _business_state()
    response = client.post(
        "/v1/hooks/telemetry/batch" if batched else "/v1/hooks/evaluate",
        json=_batch(body) if batched else body,
    )
    assert response.status_code == 400 or response.json().get("outcome") == "denied"
    assert _business_state() == before
    _capability(response)


def test_batch_accepts_mixed_exclusive_scopes(machine_client, tmp_path):
    client, actor, machine = machine_client
    project, org = str(uuid4()), str(uuid4())
    project_body = _request(project, machine, tmp_path)
    project_body["project_id"] = 1
    response = client.post(
        "/v1/hooks/telemetry/batch",
        json=_batch(project_body, _request(org, machine, tmp_path)),
    )
    assert response.status_code == 200 and response.json()["accepted"] == 2, (
        response.text
    )
    assert (
        _stored_session(project)["project_id"],
        _stored_session(project)["org_id"],
    ) == (1, None)
    row = _stored_session(org)
    assert (
        row["project_id"] is None
        and row["org_id"] is not None
        and row["actor_id"] == actor
    )
    project_body["project_id"] = 999
    response = client.post("/v1/hooks/telemetry/batch", json=_batch(project_body))
    assert response.status_code == 200, response.text
    row = _stored_session(project)
    assert (row["project_id"], row["org_id"], row["actor_id"]) == (1, None, actor)
