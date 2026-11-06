"""A delayed worker may recover its own uncontested launch on both databases."""

from __future__ import annotations

import json
from uuid import uuid4

import pytest

from runtime.api.domain.session_launch_test_support import launch_connection
from runtime.api.fixtures.backlog import insert_item
from yoke_contracts.session_control.capabilities import SESSION_SURFACE_CAPABILITIES
from yoke_contracts.timestamps import parse_instant
from yoke_core.domain import db_backend
from yoke_core.domain.session_launch_deadlines import settle_launch_deadlines
from yoke_core.domain.session_launch_registration import prepare_launch_registration
from yoke_core.domain.session_launch_store import (
    attestation_digest, get_launch, marker, update_launch,
)
from yoke_core.domain.session_launch_types import SessionLaunchError
from yoke_core.domain.session_message_receipts import acknowledge_message
from yoke_core.domain.session_message_types import SessionMessageError
from yoke_core.domain.work_claim_targets import make_item_target

NOW = "2026-08-22T12:00:00Z"
DEADLINE = "2026-08-22T12:10:00Z"
LATE = "2026-09-22T12:00:00Z"


@pytest.fixture(params=["sqlite", "postgres"])
def context(request):
    if request.param == "sqlite":
        conn = launch_connection()
        conn.execute("ALTER TABLE harness_sessions ADD COLUMN actor_id INTEGER")
        conn.execute("ALTER TABLE harness_sessions ADD COLUMN offered_at TEXT")
        item_id, project_id, actor_id = 41, 10, 1
        conn.execute("INSERT INTO items(id) VALUES (41)")
    else:
        conn = request.getfixturevalue("test_db")
        item = insert_item(conn, project="delayed-worker", workflow_id="dash", status="idea")
        item_id, project_id = item["id"], item["project_id"]
        actor_id = conn.execute("SELECT id FROM actors WHERE kind='human' LIMIT 1").fetchone()[0]
    yield conn, item_id, project_id, actor_id
    if request.param == "sqlite":
        conn.close()


def seed(context, *, surface="codex-cli", bound=True):
    conn, item_id, project_id, actor_id = context
    p = marker(conn)
    session, launch, message = (str(uuid4()) for _ in range(3))
    if db_backend.connection_is_postgres(conn):
        conn.execute(
            "INSERT INTO harness_sessions(session_id,project_id,executor,provider,workspace,"
            "execution_level,executor_surface,executor_version,model,actor_id,offered_at) "
            "VALUES (%s,%s,'codex','openai','/project','SENIOR',%s,%s,'gpt-5',%s,%s)",
            (session, project_id, surface, SESSION_SURFACE_CAPABILITIES[surface].minimum_version, actor_id, NOW),
        )
    else:
        conn.execute(
            "INSERT INTO harness_sessions(session_id,project_id,executor_surface,executor_version,model,actor_id,offered_at) "
            "VALUES (?,?,?,?,?,?,?)",
            (session, project_id, surface, SESSION_SURFACE_CAPABILITIES[surface].minimum_version, 'gpt-5', actor_id, NOW),
        )
    conn.execute(
        "INSERT INTO session_messages(message_id,sender_actor_id,body,body_sha256,selector_snapshot,created_at,expires_at) "
        f"VALUES ({','.join([p]*7)})",
        (message, actor_id, "Claim your assigned item", "fixture", "{}", NOW, DEADLINE),
    )
    columns = "launch_id,requester_actor_id,project_id,item_id,message_id,state,native_session_id,attestation_hash,deadline_at,created_at,launching_at,awaiting_registration_at,requested_surface,selected_surface"
    conn.execute(
        f"INSERT INTO session_launches({columns}) VALUES ({','.join([p]*14)})",
        (launch, actor_id, project_id, item_id, message, "awaiting_registration", session,
         attestation_digest("secret"), DEADLINE, NOW, NOW, NOW, surface, surface),
    )
    conn.commit()
    if bound:
        prepare_launch_registration(conn, launch_id=launch, attestation="secret", session_id=session, now=NOW)
    return get_launch(conn, launch), session


def claim(context, session, *, at=LATE):
    conn, item_id, _project, _actor = context
    p = marker(conn)
    conn.execute(
        "INSERT INTO work_claims(session_id,target_kind,scope,claim_type,claimed_at,last_heartbeat) "
        f"VALUES ({p},'item',{p},'exclusive',{p},{p})",
        (session, make_item_target(item_id).scope_json(), at, at),
    )
    conn.commit()


@pytest.mark.parametrize("surface", list(SESSION_SURFACE_CAPABILITIES))
@pytest.mark.parametrize("swept", [False, True])
def test_late_acknowledgement_then_claim_succeeds(context, surface, swept):
    conn, *_ = context
    launch, session = seed(context, surface=surface)
    if swept:
        settle_launch_deadlines(conn, launch_id=launch.launch_id, now=DEADLINE)
    result = acknowledge_message(conn, message_id=launch.message_id, session_id=session, now=parse_instant(LATE))
    assert next(r for r in result["recipients"] if r["session_id"] == session)["state"] == "acknowledged"
    recovered = get_launch(conn, launch.launch_id)
    assert recovered.state == "awaiting_registration"
    assert recovered.deadline_at > parse_instant(LATE)
    assert json.loads(recovered.result_evidence)["accepted_late"]["session_id"] == session
    claim(context, session)
    settled = settle_launch_deadlines(conn, launch_id=launch.launch_id, now=LATE)
    assert settled[0].state == "succeeded"


@pytest.mark.parametrize("surface", list(SESSION_SURFACE_CAPABILITIES))
def test_registration_after_deadline_succeeds(context, surface):
    conn, *_ = context
    launch, session = seed(context, surface=surface, bound=False)
    failed = settle_launch_deadlines(conn, launch_id=launch.launch_id, now=DEADLINE)[0]
    assert failed.result_code == "registration_deadline"
    prepare_launch_registration(conn, launch_id=launch.launch_id, attestation="secret", session_id=session, now=LATE)
    recovered = get_launch(conn, launch.launch_id)
    assert recovered.registered_session_id == session
    assert json.loads(recovered.result_evidence)["accepted_late"]["previous_result"] == "registration_deadline"
    acknowledge_message(conn, message_id=launch.message_id, session_id=session, now=parse_instant(LATE))
    claim(context, session)
    assert settle_launch_deadlines(conn, launch_id=launch.launch_id, now=LATE)[0].state == "succeeded"


@pytest.mark.parametrize("takeover", ["retry", "replacement", "claim", "cancelled"])
@pytest.mark.parametrize("operation", ["acknowledge", "register"])
def test_takeover_refuses_late_worker(context, takeover, operation):
    conn, *_ = context
    launch, session = seed(context, bound=operation == "acknowledge")
    settle_launch_deadlines(conn, launch_id=launch.launch_id, now=DEADLINE)
    if takeover == "retry":
        update_launch(conn, launch.launch_id, state="assigned", registered_session_id=None,
                      native_session_id=None, attestation_hash=None, attestation_consumed_at=None)
        expected = "retry"
    elif takeover == "replacement":
        replacement, _ = seed(context)
        expected = replacement.launch_id
    elif takeover == "claim":
        _, other = seed(context)
        claim(context, other)
        expected = other
    else:
        update_launch(conn, launch.launch_id, state="cancelled")
        expected = "cancelled"
    conn.commit()
    with pytest.raises((SessionLaunchError, SessionMessageError)) as refused:
        if operation == "acknowledge":
            acknowledge_message(conn, message_id=launch.message_id, session_id=session, now=parse_instant(LATE))
        else:
            prepare_launch_registration(conn, launch_id=launch.launch_id, attestation="secret", session_id=session, now=LATE)
    assert refused.value.code == "launch_taken_over"
    assert expected in str(refused.value)
    assert "Stop this worker" in str(refused.value)
    assert get_launch(conn, launch.launch_id).state != "awaiting_registration"
