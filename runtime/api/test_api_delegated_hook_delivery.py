"""Project-scoped hooks use the actor of a live attested launch."""

from __future__ import annotations

import json
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from runtime.api.fixtures.actor_roles import seed_project_role
from runtime.api.fixtures.pg_testdb import test_database
from runtime.api.fixtures.session_holdings import insert_session
from runtime.api.test_api_launch_machine_actor import _seed
from yoke_contracts.hook_evaluator_protocol import attach_evaluator_metadata
from yoke_contracts.timestamps import utc_now
from yoke_core.api.main import app
from yoke_core.domain.actor_permissions import ROLE_OWNER
from yoke_core.domain.actors import seed_human_actor
from yoke_core.domain.api_tokens import mint_token
from yoke_core.domain.session_launch_abandonment import settle_abandoned_launch


def _hook(session, machine, project, cwd, *, tool, event, timing=""):
    return {
        "event_name": event,
        "executor": "codex",
        "entrypoint": "codex-cli",
        "project_id": project,
        "machine_id": machine,
        "stdin": attach_evaluator_metadata(
            json.dumps(
                {
                    "identity_stamped": True,
                    "session_id": session,
                    "tool_name": tool,
                    "tool_use_id": "completed-call",
                    "tool_input": {"file_path": str(cwd / "data.txt")},
                    "tool_response": {"content": "ok"},
                    "cwd": str(cwd),
                }
            ),
            evaluator="resident",
            warm_duration_ms=1,
            client_timing_id=timing,
        ),
    }


def _observation(hook):
    return {
        "observation_id": str(uuid4()),
        "observed_at": utc_now().isoformat(),
        "hook_wait_ms": 1,
        "hook_request": hook,
    }


def _headers(token):
    return {"Authorization": f"Bearer {token.raw_token}"}


def _third_actor_token(conn, machine):
    actor = seed_human_actor(conn, "unrelated operator")
    token = mint_token(conn, actor_id=actor, name="third-actor-machine-token")
    conn.execute(
        "UPDATE api_tokens SET machine_id=%s WHERE id=%s", (machine, token.token_id)
    )
    conn.commit()
    return token


def _wall(client, token, timing):
    return client.post(
        "/v1/hooks/telemetry/client-wall",
        headers=_headers(token),
        json={"client_wall_reports": [{"event_id": timing, "client_wall_ms": 50}]},
    )


@pytest.mark.parametrize("batch", [False, True], ids=["synchronous", "read-only-batch"])
def test_delegated_hook_completion_keeps_itemless_launch_succeeded(tmp_path, batch):
    with test_database() as conn:
        requester, owner_actor, owner, machine, _, session, message = _seed(conn)
        seed_project_role(
            conn,
            actor_id=owner_actor,
            project_id=requester.project_id,
            role_name=ROLE_OWNER,
            granted_by_actor_id=requester.actor_id,
        )
        owner_session = str(uuid4())
        insert_session(conn, owner_session)
        conn.execute(
            "UPDATE harness_sessions SET actor_id=%s,machine_id=%s WHERE session_id=%s",
            (owner_actor, machine, owner_session),
        )
        conn.execute(
            "UPDATE session_message_recipients SET state='acknowledged',acknowledged_at=%s "
            "WHERE message_id=%s AND session_id=%s",
            (utc_now(), message, session),
        )
        conn.execute(
            "UPDATE session_launches SET state='succeeded',result_code='registered_and_acknowledged' "
            "WHERE message_id=%s",
            (message,),
        )
        conn.commit()
        third = _third_actor_token(conn, machine)
        timing = str(uuid4())
        tool = "Read" if batch else "Write"
        with TestClient(app) as client:
            if batch:
                observations = [
                    _observation(
                        _hook(
                            sid,
                            machine,
                            requester.project_id,
                            tmp_path,
                            tool=tool,
                            event=event,
                            timing=timing
                            if sid == session and event == "PostToolUse"
                            else "",
                        )
                    )
                    for event in ("PreToolUse", "PostToolUse")
                    for sid in (owner_session, session)
                ]
                response = client.post(
                    "/v1/hooks/telemetry/batch",
                    headers=_headers(owner),
                    json={"observations": observations},
                )
                assert response.status_code == 200, response.text
                assert response.json()["accepted"] == 4
            else:
                response = client.post(
                    "/v1/hooks/evaluate",
                    headers=_headers(owner),
                    json=_hook(
                        session,
                        machine,
                        requester.project_id,
                        tmp_path,
                        tool=tool,
                        event="PostToolUse",
                        timing=timing,
                    ),
                )
                assert response.status_code == 200, response.text
                assert response.json()["outcome"] == "completed", response.text

            refused = _wall(client, third, timing)
            assert refused.status_code == 403, refused.text
            assert refused.json()["error"]["code"] == "HOOK_CLIENT_WALL_ACTOR_DENIED"
            accepted = _wall(client, owner, timing)
            assert accepted.status_code == 200, accepted.text

            final_timing = str(uuid4())
            terminal = client.post(
                "/v1/hooks/evaluate",
                headers=_headers(owner),
                json=_hook(
                    session,
                    machine,
                    requester.project_id,
                    tmp_path,
                    tool=tool,
                    event="SessionEnd",
                    timing=final_timing,
                ),
            )
            assert terminal.json()["outcome"] == "completed", terminal.text
            assert _wall(client, owner, final_timing).status_code == 200

        dispatches = conn.execute(
            "SELECT session_id,actor_id,envelope FROM events "
            "WHERE event_name='HookDispatchTelemetry' AND hook_event_name='PostToolUse' "
            "AND session_id IN (%s,%s)",
            (session, owner_session),
        ).fetchall()
        stamps = {row[0]: row[1] for row in dispatches}
        assert stamps[session] == requester.actor_id
        if batch:
            assert stamps[owner_session] == owner_actor
        terminal_dispatch = conn.execute(
            "SELECT actor_id,client_timing_id FROM events "
            "WHERE event_name='HookDispatchTelemetry' AND hook_event_name='SessionEnd' "
            "AND session_id=%s",
            (session,),
        ).fetchone()
        assert tuple(terminal_dispatch) == (requester.actor_id, None)
        dispatch = next(row for row in dispatches if row[0] == session)
        assert json.loads(dispatch[2])["context"]["client_wall_ms"] >= 50
        state = conn.execute(
            "SELECT actor_id,first_completed_work_at,tool_call_count,ended_at FROM harness_sessions "
            "WHERE session_id=%s",
            (session,),
        ).fetchone()
        assert state[0] == requester.actor_id
        assert state[1] is not None
        assert state[2] >= 1
        assert state[3] is not None
        assert (
            settle_abandoned_launch(conn, session, end_reason="session_ended") is None
        )
        launch = conn.execute(
            "SELECT state FROM session_launches WHERE message_id=%s", (message,)
        ).fetchone()
        assert launch[0] == "succeeded"


@pytest.mark.parametrize(
    "exact_launch", [False, True], ids=["no-launch", "non-owner-token"]
)
def test_hook_routes_refuse_unrelated_actor(tmp_path, exact_launch):
    with test_database() as conn:
        requester, _, owner, machine, _, session, _ = _seed(conn)
        if exact_launch:
            token = _third_actor_token(conn, machine)
        else:
            session = str(uuid4())
            insert_session(conn, session)
            conn.execute(
                "UPDATE harness_sessions SET actor_id=%s,machine_id=%s WHERE session_id=%s",
                (requester.actor_id, machine, session),
            )
            conn.commit()
            token = owner
        hook = _hook(
            session,
            machine,
            requester.project_id,
            tmp_path,
            tool="Read",
            event="PostToolUse",
        )
        with TestClient(app) as client:
            synchronous = client.post(
                "/v1/hooks/evaluate", headers=_headers(token), json=hook
            )
            assert synchronous.json()["outcome"] == "denied", synchronous.text
            assert "HOOK_SESSION_DENIED" in synchronous.json()["stdout"]
            batch = client.post(
                "/v1/hooks/telemetry/batch",
                headers=_headers(token),
                json={"observations": [_observation(hook)]},
            )
            assert batch.status_code == 403, batch.text
            assert batch.json()["error"]["code"] == "HOOK_OBSERVATION_SESSION_DENIED"
        state = conn.execute(
            "SELECT first_completed_work_at FROM harness_sessions WHERE session_id=%s",
            (session,),
        ).fetchone()
        assert state[0] is None
