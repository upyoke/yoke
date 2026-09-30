"""A relay machine may act only for its exact attested launched session."""

from __future__ import annotations

import hashlib
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from runtime.api.auth_test_helpers import mint_api_auth_context
from runtime.api.fixtures.pg_testdb import test_database
from runtime.api.fixtures.session_holdings import insert_session
from yoke_core.api.launch_machine_actor import _delegated_actor
from yoke_core.api.main import app
from yoke_core.domain.actors import seed_human_actor
from yoke_core.domain.api_tokens import mint_token
from yoke_core.domain.handlers.__init_register__ import register_all_handlers
from yoke_core.domain.yoke_function_registry import reset_registry_for_tests


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _seed(conn):
    requester = mint_api_auth_context(conn)
    machine_actor = seed_human_actor(conn, "relay machine owner")
    token = mint_token(conn, actor_id=machine_actor, name="relay-machine")
    machine_id = str(uuid.uuid4())
    other_machine = str(uuid.uuid4())
    session_id = str(uuid.uuid4())
    message_id = str(uuid.uuid4())
    launch_id = str(uuid.uuid4())
    now = _now()
    future = (datetime.now(timezone.utc) + timedelta(hours=1)).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )
    conn.execute(
        "INSERT INTO machines (machine_id,name,owner_actor_id,access,registered_at) "
        "VALUES (%s,'relay',%s,'{}',%s)",
        (machine_id, machine_actor, now),
    )
    conn.execute(
        "UPDATE api_tokens SET machine_id=%s WHERE id=%s",
        (machine_id, token.token_id),
    )
    insert_session(conn, session_id)
    conn.execute(
        "UPDATE harness_sessions SET actor_id=%s,machine_id=%s,project_id=%s "
        "WHERE session_id=%s",
        (requester.actor_id, machine_id, requester.project_id, session_id),
    )
    body = "Read and acknowledge this launch mandate."
    conn.execute(
        "INSERT INTO session_messages "
        "(message_id,sender_actor_id,body,body_sha256,selector_snapshot,created_at,expires_at) "
        "VALUES (%s,%s,%s,%s,'{}',%s,%s)",
        (
            message_id,
            requester.actor_id,
            body,
            hashlib.sha256(body.encode()).hexdigest(),
            now,
            future,
        ),
    )
    conn.execute(
        "INSERT INTO session_launches "
        "(launch_id,requester_actor_id,project_id,requested_surface,selected_surface,"
        "message_id,state,assigned_machine_id,native_session_id,registered_session_id,"
        "attestation_consumed_at,deadline_at,created_at) "
        "VALUES (%s,%s,%s,'codex-cli','codex-cli',%s,'awaiting_registration',"
        "%s,%s,%s,%s,%s,%s)",
        (
            launch_id,
            requester.actor_id,
            requester.project_id,
            message_id,
            machine_id,
            session_id,
            session_id,
            now,
            future,
            now,
        ),
    )
    conn.execute(
        "INSERT INTO session_message_recipients "
        "(message_id,session_id,project_id,resolution_evidence,routing_snapshot,"
        "state,created_at,wake_after) "
        "VALUES (%s,%s,%s,'{}','{}','injected',%s,%s)",
        (message_id, session_id, requester.project_id, now, now),
    )
    conn.commit()
    return (
        requester,
        machine_actor,
        token,
        machine_id,
        other_machine,
        session_id,
        message_id,
    )


def test_cross_owner_machine_credential_acknowledges_exact_launch() -> None:
    reset_registry_for_tests()
    register_all_handlers()
    try:
        with test_database() as conn:
            requester, machine_actor, token, machine_id, _, session_id, message_id = (
                _seed(conn)
            )
            assert requester.actor_id != machine_actor
            assert (
                _delegated_actor(
                    session_id=session_id,
                    machine_id=machine_id,
                    token_actor_id=machine_actor,
                )
                == requester.actor_id
            )
            with TestClient(app) as client:
                response = client.post(
                    "/v1/functions/call",
                    json={
                        "function": "session_control.message.acknowledge",
                        "version": "v1",
                        "actor": {"session_id": session_id, "actor_id": "spoofed"},
                        "target": {"kind": "global"},
                        "payload": {"message_id": message_id},
                    },
                    headers={"Authorization": f"Bearer {token.raw_token}"},
                )
            assert response.status_code == 200, response.text
            assert response.json()["success"] is True
            recipient = conn.execute(
                "SELECT state FROM session_message_recipients "
                "WHERE message_id=%s AND session_id=%s",
                (message_id, session_id),
            ).fetchone()
            launch = conn.execute(
                "SELECT state,result_code FROM session_launches WHERE message_id=%s",
                (message_id,),
            ).fetchone()
            assert recipient[0] == "acknowledged"
            assert tuple(launch) == ("succeeded", "registered_and_acknowledged")
    finally:
        reset_registry_for_tests()


@pytest.mark.parametrize(
    "broken_link",
    [
        "different_machine",
        "wrong_machine_owner",
        "wrong_requester",
        "wrong_native_session",
        "missing_attestation",
        "failed_launch",
        "ended_session",
        "retired_machine",
    ],
)
def test_machine_delegation_requires_every_launch_binding(broken_link: str) -> None:
    with test_database() as conn:
        requester, machine_actor, _, machine_id, other_machine, session_id, _ = _seed(
            conn
        )
        if broken_link == "different_machine":
            machine_id = other_machine
        elif broken_link == "wrong_machine_owner":
            machine_actor = requester.actor_id
        elif broken_link == "wrong_requester":
            conn.execute(
                "UPDATE session_launches SET requester_actor_id=%s WHERE registered_session_id=%s",
                (machine_actor, session_id),
            )
        elif broken_link == "wrong_native_session":
            conn.execute(
                "UPDATE session_launches SET native_session_id=%s WHERE registered_session_id=%s",
                (str(uuid.uuid4()), session_id),
            )
        elif broken_link == "missing_attestation":
            conn.execute(
                "UPDATE session_launches SET attestation_consumed_at=NULL "
                "WHERE registered_session_id=%s",
                (session_id,),
            )
        elif broken_link == "failed_launch":
            conn.execute(
                "UPDATE session_launches SET state='failed' WHERE registered_session_id=%s",
                (session_id,),
            )
        elif broken_link == "ended_session":
            conn.execute(
                "UPDATE harness_sessions SET ended_at=%s WHERE session_id=%s",
                (_now(), session_id),
            )
        elif broken_link == "retired_machine":
            conn.execute(
                "UPDATE machines SET retired_at=%s WHERE machine_id=%s",
                (_now(), machine_id),
            )
        conn.commit()
        assert (
            _delegated_actor(
                session_id=session_id,
                machine_id=machine_id,
                token_actor_id=machine_actor,
            )
            is None
        )
