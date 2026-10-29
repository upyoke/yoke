"""Token-actor binding for relay-registered sessions.

Sibling of ``test_api_hooks_evaluate_route.py`` (350-line cap) sharing its
DB/client fixtures via import.
"""

from __future__ import annotations

import json
from uuid import uuid4

import pytest

from runtime.api.api_items_test_helpers import (
    _client_for_db,
    make_test_db_fixture,
)
from runtime.api.test_api_hooks_evaluate_route import _request_body
from yoke_core.domain import db_helpers


def _stored_session(session):
    with db_helpers.connect() as conn:
        row = conn.execute(
            "SELECT * FROM harness_sessions WHERE session_id=%s", (session,)
        ).fetchone()
        return dict(row) if row is not None else None


@pytest.fixture()
def hooks_db():
    yield from make_test_db_fixture()


@pytest.fixture()
def client(hooks_db):
    with _client_for_db(hooks_db["db_path"]) as authed:
        yield authed


@pytest.fixture()
def machine_client(client):
    from yoke_core.domain import api_tokens, db_helpers, machine_credentials
    from yoke_contracts.timestamps import utc_now

    with db_helpers.connect() as conn:
        account = api_tokens.verify_token(
            conn, client.headers["authorization"].split(" ", 1)[1]
        )
        machine = str(uuid4())
        credential = machine_credentials.register_with_credential(
            conn,
            machine_id=machine,
            name="hook-client",
            actor_id=account.actor_id,
            now=utc_now(),
        )[2]
        verified = api_tokens.verify_token(conn, credential.token)
        assert (verified.actor_id, verified.machine_id) == (account.actor_id, machine)
    client.headers["authorization"] = f"Bearer {credential.token}"
    return client, account.actor_id, machine


@pytest.mark.parametrize("executor", ["claude", "codex", "cursor"])
@pytest.mark.parametrize("event", ["SessionStart", "UserPromptSubmit", "PreToolUse"])
def test_machine_hook_registers_real_authenticated_row(
    machine_client, tmp_path, executor, event
):
    client, actor, machine = machine_client
    session = str(uuid4())
    body = _request_body(
        executor=executor,
        event_name=event,
        project_id=None,
        machine_id=machine,
        stdin=json.dumps(
            {
                "session_id": session,
                "identity_stamped": True,
                "cwd": str(tmp_path),
                "project_id": 1,
                "tool_name": "Read",
                "tool_input": {"file_path": str(tmp_path / "note")},
                # A Codex hook registers only from a saved transcript.
                **(
                    {"transcript_path": str(tmp_path / "rollout.jsonl")}
                    if executor == "codex"
                    else {}
                ),
            }
        ),
    )
    response = client.post("/v1/hooks/evaluate", json=body)
    assert response.status_code == 200
    assert response.json()["outcome"] == "completed", response.json()
    row = _stored_session(session)
    assert row is not None, response.json()
    assert row["project_id"] is None and row["org_id"] is not None
    assert row["actor_id"] == actor
    assert (
        row["executor"]
        == {"claude": "claude-code", "codex": "codex", "cursor": "cursor"}[executor]
    )
    assert row["machine_id"] == machine
    assert row["workspace"] == str(tmp_path)


def test_hooks_evaluate_binds_token_actor_at_relayed_registration(
    client,
    hooks_db,
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
        stdin=json.dumps(
            {
                "tool_name": "Bash",
                "tool_input": {"command": "true"},
                "cwd": "/client/repo",
                "session_id": session_id,
                "project_id": 1,
            }
        ),
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


def _machine_request(session, machine, workspace, **extra):
    return _request_body(
        event_name="SessionStart",
        project_id=None,
        machine_id=machine,
        stdin=json.dumps(
            {"session_id": session, "identity_stamped": True, "cwd": str(workspace)}
        ),
        **extra,
    )


@pytest.mark.parametrize("refusal", ["unbound", "mismatch", "nonmember", "foreign"])
def test_machine_credential_and_session_refusals_do_not_mutate(
    machine_client,
    tmp_path,
    monkeypatch,
    refusal,
):
    from yoke_core.domain import api_tokens, db_helpers, actors

    client, actor, machine = machine_client
    session = str(uuid4())
    request = _machine_request(session, machine, tmp_path)
    with db_helpers.connect() as conn:
        if refusal == "unbound":
            token = api_tokens.mint_token(conn, actor_id=actor, name="unbound")
            client.headers["authorization"] = f"Bearer {token.raw_token}"
        elif refusal == "mismatch":
            request["machine_id"] = str(uuid4())
        elif refusal == "nonmember":
            conn.execute("DELETE FROM actor_org_roles WHERE actor_id=%s", (actor,))
        else:
            assert (
                client.post("/v1/hooks/evaluate", json=request).json()["outcome"]
                == "completed"
            )
            other = actors.seed_system_actor(conn, "other-hook-actor")
            conn.execute(
                "UPDATE harness_sessions SET actor_id=%s WHERE session_id=%s",
                (other, session),
            )
        conn.commit()
        before = conn.execute(
            "SELECT * FROM harness_sessions WHERE session_id=%s", (session,)
        ).fetchone()
    scratch = tmp_path / "scratch"
    monkeypatch.setenv("YOKE_SCRATCH_ROOT", str(scratch))
    response = client.post("/v1/hooks/evaluate", json=request)
    code = {
        "unbound": "machine_credential_required",
        "mismatch": "machine_credential_mismatch",
        "nonmember": "SESSION_ORG_MEMBERSHIP_REQUIRED",
        "foreign": "HOOK_SESSION_DENIED",
    }[refusal]
    assert response.json()["outcome"] == "denied"
    assert (
        code in response.json()["stdout"] and "Recovery:" in response.json()["stdout"]
    )
    assert not list(scratch.rglob("dispatch-server-*"))
    assert _stored_session(session) == before


def test_stored_org_scope_and_authenticated_identity_dominate_payload(
    machine_client, tmp_path
):
    client, actor, machine = machine_client
    session, forged = str(uuid4()), str(uuid4())
    request = _machine_request(session, machine, tmp_path)
    assert (
        client.post("/v1/hooks/evaluate", json=request).json()["outcome"] == "completed"
    )
    request["project_id"] = 1
    request["event_name"] = "PreToolUse"
    request["payload_extra"] = {
        "session_id": forged,
        "project_id": 1,
        "actor_id": actor + 100,
        "org_id": 999,
        "machine_id": "forged",
    }
    assert (
        client.post("/v1/hooks/evaluate", json=request).json()["outcome"] == "completed"
    )
    row = _stored_session(session)
    assert row["project_id"] is None and row["org_id"] != 999
    assert (row["actor_id"], row["machine_id"]) == (actor, machine)
    assert _stored_session(forged) is None


def test_stored_project_cannot_escape_project_authorization(machine_client, tmp_path):
    from yoke_core.domain import db_helpers

    client, actor, machine = machine_client
    session = str(uuid4())
    request = _machine_request(session, machine, tmp_path)
    request["project_id"] = 1
    assert (
        client.post("/v1/hooks/evaluate", json=request).json()["outcome"] == "completed"
    )
    request["project_id"] = None
    assert (
        client.post("/v1/hooks/evaluate", json=request).json()["outcome"] == "completed"
    )
    with db_helpers.connect() as conn:
        before = conn.execute(
            "SELECT * FROM harness_sessions WHERE session_id=%s", (session,)
        ).fetchone()
        assert before["project_id"] == 1 and before["org_id"] is None
        conn.execute("DELETE FROM actor_project_roles WHERE actor_id=%s", (actor,))
        conn.execute("DELETE FROM actor_org_roles WHERE actor_id=%s", (actor,))
        conn.commit()
    response = client.post("/v1/hooks/evaluate", json=request).json()
    assert (
        response["outcome"] == "denied" and "HOOK_PROJECT_DENIED" in response["stdout"]
    )
    assert _stored_session(session) == before


def test_real_machine_dispatch_uses_actor_scratch_and_restores_context(
    machine_client, tmp_path, monkeypatch
):
    from yoke_core.domain import (
        actors,
        db_helpers,
        machine_credentials,
        project_scratch_dir as scratch,
    )
    from yoke_core.domain.actor_permissions import ROLE_ADMIN, grant_actor_org_role
    from yoke_core.domain.external_identities import default_org_id
    from yoke_contracts.timestamps import utc_now

    client, actor, machine = machine_client
    monkeypatch.setenv("YOKE_SCRATCH_ROOT", str(tmp_path / "scratch"))
    monkeypatch.setenv("YOKE_PROJECT", "externalwebapp")
    paths = []
    for owner in [actor, None]:
        if owner is None:
            with db_helpers.connect() as conn:
                owner = actors.seed_system_actor(conn, "second-hook-actor")
                grant_actor_org_role(
                    conn,
                    actor_id=owner,
                    org_id=default_org_id(conn),
                    role_name=ROLE_ADMIN,
                    granted_by_actor_id=actor,
                )
                machine = str(uuid4())
                credential = machine_credentials.register_with_credential(
                    conn,
                    machine_id=machine,
                    name="second-client",
                    actor_id=owner,
                    now=utc_now(),
                )[2]
                client.headers["authorization"] = f"Bearer {credential.token}"
        session = str(uuid4())
        assert (
            client.post(
                "/v1/hooks/evaluate", json=_machine_request(session, machine, tmp_path)
            ).json()["outcome"]
            == "completed"
        )
        with scratch.scratch_machine_owner(owner):
            marker = scratch.hook_marker_path(f"dispatch-server-SessionStart-{session}")
            cache = scratch.harness_runtime_cache_path("identity")
        assert marker.exists() and f"actor-{owner}" in str(marker)
        paths.append((marker.parent, cache.parent))
    assert paths[0][0] != paths[1][0] and paths[0][1] != paths[1][1]
    assert "actor-" not in str(scratch.hook_marker_path("restored"))
