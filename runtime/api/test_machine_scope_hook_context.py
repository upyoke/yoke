"""Concurrent hook scratch and completion context retain authenticated scope."""

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
import json
import os
import subprocess
import sys
from uuid import uuid4

import pytest

from runtime.api.test_machine_scope_hook_routes import _request
from runtime.api.test_api_hooks_evaluate_route_actor import _stored_session
from yoke_contracts.timestamps import utc_now
from yoke_core.domain import db_helpers

pytest_plugins = ("runtime.api.test_api_hooks_evaluate_route_actor",)


def test_remote_machine_scope_scratch_isolated_per_actor(
    machine_client, tmp_path, monkeypatch
):
    from yoke_core.domain import (
        actors,
        machine_credentials,
        project_scratch_dir as scratch,
    )
    from yoke_core.domain.actor_permissions import ROLE_ADMIN, grant_actor_org_role
    from yoke_core.domain.external_identities import default_org_id
    from yoke_core.hooks import remote_entry

    client, actor, machine = machine_client
    identities = [(actor, machine, client.headers["authorization"])]
    with db_helpers.connect() as conn:
        other = actors.seed_system_actor(conn, "concurrent-hook-owner")
        grant_actor_org_role(
            conn,
            actor_id=other,
            org_id=default_org_id(conn),
            role_name=ROLE_ADMIN,
            granted_by_actor_id=actor,
        )
        machine = str(uuid4())
        credential = machine_credentials.register_with_credential(
            conn,
            machine_id=machine,
            name="second-client",
            actor_id=other,
            now=utc_now(),
        )[2]
        identities.append((other, machine, f"Bearer {credential.token}"))
    monkeypatch.setenv("YOKE_PROJECT", "externalwebapp")
    monkeypatch.setenv("YOKE_SCRATCH_ROOT", str(tmp_path / "scratch"))
    barrier, paths, original = Barrier(2), {}, remote_entry.run_event

    def overlapping(*args, **kwargs):
        owner = kwargs["controls"].actor_id
        paths[owner] = (
            scratch.hook_marker_path("concurrent"),
            scratch.harness_runtime_cache_path("identity"),
        )
        barrier.wait(timeout=10)
        result = original(*args, **kwargs)
        barrier.wait(timeout=10)
        return result

    monkeypatch.setattr(remote_entry, "run_event", overlapping)

    def invoke(identity):
        owner, machine, token = identity
        session = str(uuid4())
        response = client.post(
            "/v1/hooks/evaluate",
            headers={"authorization": token},
            json=_request(session, machine, tmp_path, event="SessionStart"),
        )
        assert response.json()["outcome"] == "completed", response.text
        assert _stored_session(session)["actor_id"] == owner
        with scratch.scratch_machine_owner(owner):
            assert scratch.hook_marker_path(
                f"dispatch-server-SessionStart-{session}"
            ).exists()
        return owner

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert set(pool.map(invoke, identities)) == {actor, other}
    assert paths[actor][0].parent != paths[other][0].parent
    assert paths[actor][1].parent != paths[other][1].parent
    assert all(
        f"actor-{owner}" in str(path) for owner in paths for path in paths[owner]
    )
    assert "actor-" not in str(scratch.hook_marker_path("restored"))


@pytest.mark.parametrize("project", [None, "client-project"])
def test_process_context_keeps_project_optional_and_restores_parent(
    monkeypatch, tmp_path, project
):
    from yoke_contracts import hook_process_context as process

    monkeypatch.setenv("YOKE_PROJECT", "server-project")
    environment = {} if project is None else {"YOKE_PROJECT": project}
    context = process.HookProcessContext(
        environment=environment, cwd=str(tmp_path), pid=123, ppid=122
    )
    with monkeypatch.context() as patch:
        for module, names in [
            (os, ("environ", "getcwd", "getpid", "getppid")),
            (sys, ("stdout", "stderr")),
            (subprocess, ("Popen",)),
            (process, ("_INSTALLED",)),
        ]:
            for name in names:
                patch.setattr(module, name, getattr(module, name))
        patch.setattr(process, "_INSTALLED", False)
        process.install_process_context()
        with process.activate_process_context(context):
            assert os.environ.get("YOKE_PROJECT") == project
            assert os.getcwd() == str(tmp_path) and os.getpid() == 123
        assert os.environ["YOKE_PROJECT"] == "server-project"
    assert process.active_output_capture() is None


@pytest.mark.parametrize("scope", ["org", "foreign_org", "project_denied"])
def test_client_wall_keeps_org_ownership_and_project_security(
    machine_client, tmp_path, scope
):
    from runtime.api.fixtures.backlog import insert_event
    from yoke_core.domain import actors, api_tokens

    client, actor, machine = machine_client
    timing, event, session = str(uuid4()), str(uuid4()), str(uuid4())
    if scope != "project_denied":
        response = client.post(
            "/v1/hooks/evaluate",
            json=_request(session, machine, tmp_path, event="SessionStart"),
        )
        assert response.json()["outcome"] == "completed", response.text
        row = _stored_session(session)
        assert row["project_id"] is None and row["org_id"] is not None
        assert row["actor_id"] == actor
    with db_helpers.connect() as conn:
        other = actors.seed_system_actor(conn, "other-wall-owner")
        insert_event(
            conn,
            event_id=event,
            session_id=session,
            client_timing_id=timing,
            event_name="HookDispatchTelemetry",
            project_id=1 if scope == "project_denied" else None,
            actor_id=None if scope == "project_denied" else actor,
            duration_ms=3,
            envelope=json.dumps({"context": {"hook_wait_ms": 3}}),
        )
        if scope == "foreign_org":
            token = api_tokens.mint_token(conn, actor_id=other, name="foreign-wall")
            client.headers["authorization"] = f"Bearer {token.raw_token}"
        elif scope == "project_denied":
            conn.execute("DELETE FROM actor_project_roles WHERE actor_id=%s", (actor,))
            conn.execute("DELETE FROM actor_org_roles WHERE actor_id=%s", (actor,))
        conn.commit()
    response = client.post(
        "/v1/hooks/telemetry/client-wall",
        json={"client_wall_reports": [{"event_id": timing, "client_wall_ms": 42}]},
    )
    assert response.status_code == (200 if scope == "org" else 403), response.text
    with db_helpers.connect() as conn:
        row = conn.execute(
            "SELECT client_timing_id,envelope FROM events WHERE event_id=%s",
            (event,),
        ).fetchone()
        if scope == "org":
            assert row["client_timing_id"] is None
            assert json.loads(row["envelope"])["context"]["client_wall_ms"] == 42
        else:
            assert (
                row is not None
                and "client_wall_ms" not in json.loads(row["envelope"])["context"]
            )
