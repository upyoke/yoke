"""Exercise the real Conduct status pipeline without server harness identity."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from runtime.api.fixtures.backlog import insert_epic_task, insert_item
from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)
from yoke_core.domain import update_status, verify_claim
from yoke_core.domain.epic_task_scope import (
    finalize_generated_task_scopes,
    set_no_files_scope,
)
from yoke_core.domain.handlers import conduct_epic_pipeline
from yoke_core.domain.work_claim_targets import make_epic_task_target, make_item_target

EPIC_ID = 42
WORKER = "task-worker"
PARENT = "parent-holder"


def _claim(conn, session, target, *, released=False):
    conn.execute(
        "INSERT INTO harness_sessions "
        "(session_id, project_id, executor, provider, model, execution_level, workspace, mode, "
        "offered_at, last_heartbeat) VALUES (%s, (SELECT project_id FROM items "
        "WHERE id=42), 'codex', 'openai', 'test', "
        "'SENIOR', '/test', 'conduct', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP) "
        "ON CONFLICT (session_id) DO NOTHING",
        (session,),
    )
    conn.execute(
        "INSERT INTO work_claims (session_id, target_kind, scope, claimed_at, "
        "last_heartbeat, released_at) VALUES (%s, %s, %s, CURRENT_TIMESTAMP, "
        "CURRENT_TIMESTAMP, CASE WHEN %s THEN CURRENT_TIMESTAMP ELSE NULL END)",
        (session, target.kind, target.scope_json(), released),
    )
    conn.commit()


@pytest.fixture
def task(test_db, monkeypatch):
    for key in ("YOKE_SESSION_ID", "YOKE_CLAIM_BYPASS", "YOKE_STATUS_SOURCE"):
        monkeypatch.delenv(key, raising=False)
    insert_item(test_db, id=EPIC_ID, workflow_id="epic", status="implementing")
    insert_epic_task(test_db, epic_id=EPIC_ID, task_num=1, status="planned")
    set_no_files_scope(test_db, EPIC_ID, 1)
    finalize_generated_task_scopes(test_db, EPIC_ID)
    return test_db


def _start(session=WORKER, **payload):
    return conduct_epic_pipeline.handle_update_status(
        FunctionCallRequest(
            function="conduct.epic_task.update_status",
            actor=ActorContext(actor_id="1", session_id=session),
            target=TargetRef(kind="epic_task", epic_id=EPIC_ID, task_num=1),
            payload={
                "status": "implementing",
                "no_github": True,
                "no_derive": True,
                **payload,
            },
        )
    )


def _state(conn):
    row = conn.execute(
        "SELECT status, dispatch_attempts, last_heartbeat FROM epic_tasks "
        "WHERE epic_id=%s AND task_num=1",
        (EPIC_ID,),
    ).fetchone()
    return tuple(row)


@pytest.mark.parametrize("authority", ["task", "parent"])
def test_authenticated_actor_starts_with_owned_authority(task, authority):
    _claim(task, PARENT, make_item_target(EPIC_ID))
    _claim(task, WORKER, make_epic_task_target(EPIC_ID, 1))
    actor = WORKER if authority == "task" else PARENT
    with patch.object(verify_claim, "_resolve_session_id", return_value="") as ambient:
        outcome = _start(actor)
    assert outcome.primary_success, outcome.error
    ambient.assert_not_called()
    status, attempts, heartbeat = _state(task)
    assert (status, attempts) == ("implementing", 1)
    assert heartbeat is not None
    transition = task.execute(
        "SELECT from_status, to_status, source FROM item_status_transitions "
        "WHERE item_id=%s AND task_num=1 ORDER BY id DESC LIMIT 1",
        (EPIC_ID,),
    ).fetchone()
    assert tuple(transition) == ("planned", "implementing", "conduct")


@pytest.mark.parametrize("claim", ["missing", "foreign", "released", "other-task"])
def test_unauthorized_actor_cannot_start(task, claim):
    _claim(task, PARENT, make_item_target(EPIC_ID))
    if claim != "missing":
        _claim(
            task,
            "foreign-worker" if claim == "foreign" else WORKER,
            make_epic_task_target(EPIC_ID, 2 if claim == "other-task" else 1),
            released=claim == "released",
        )
    before = _state(task)
    with patch.object(verify_claim, "_resolve_session_id", return_value=PARENT):
        outcome = _start(
            session_id=PARENT
        )  # Untrusted payload identity has no authority.
    assert not outcome.primary_success
    assert outcome.error.code == "status_pipeline_failed"
    assert "Claim verification denied" in outcome.error.message
    assert "yoke claims work acquire --epic" in outcome.error.message
    assert _state(task) == before


def test_missing_actor_never_inherits_server_parent_identity(task):
    _claim(task, PARENT, make_item_target(EPIC_ID))
    with patch.object(verify_claim, "_resolve_session_id", return_value=PARENT):
        outcome = _start("")
    assert not outcome.primary_success
    assert _state(task)[:2] == ("planned", 0)


def test_retained_local_updater_resolves_ambient_session(task):
    _claim(task, PARENT, make_item_target(EPIC_ID))
    with patch.object(
        verify_claim, "_resolve_session_id", return_value=PARENT
    ) as ambient:
        rc = update_status.update_task_status(
            task,
            EPIC_ID,
            "1",
            "implementing",
            no_github=True,
            no_derive=True,
        )
    assert rc == 0
    ambient.assert_called_once_with()
    assert _state(task)[:2] == ("implementing", 1)


def test_task_claim_cannot_authorize_parent_write(task):
    _claim(task, WORKER, make_epic_task_target(EPIC_ID, 1))
    rc, result = verify_claim.verify(EPIC_ID, session_id=WORKER)
    assert rc == 1
    assert not result["verified"]


def test_authenticated_claim_does_not_skip_scope_gate(task):
    _claim(task, WORKER, make_epic_task_target(EPIC_ID, 1))
    task.execute(
        "UPDATE epic_tasks SET scope_finalized_at=NULL WHERE epic_id=%s", (EPIC_ID,)
    )
    task.commit()
    before = _state(task)
    outcome = _start()
    assert not outcome.primary_success
    assert "scope is not finalized" in outcome.error.message
    assert _state(task) == before
