"""Stored-row acting identity for lifecycle and QA events.

``events.emit_event`` stamps acting identity, and the dispatcher binds the
actor it resolved server-side, but that guarantee only reaches the ledger if
the real ``lifecycle.transition`` and ``qa.run.complete`` handlers emit
through that emitter. These tests drive the registered function-call surface
and read the stored ``events`` rows, so a handler that grew its own write
path would fail here rather than silently ship unattributed rows.

The sessionless half asserts the two ways identity stays honest when no
session is present: a mutating call carrying no session is refused before it
runs and writes no event at all, and a server-internal emission stores null
identity rather than an invented actor.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from runtime.api.fixtures.backlog_inserts import insert_item
from runtime.api.fixtures.backlog_qa_inserts import insert_qa_requirement, insert_qa_run
from runtime.api.fixtures.pg_testdb import test_database
from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)
from yoke_core.domain import local_operating_actor
from yoke_core.domain import db_helpers
from yoke_core.domain import events_acting_identity
from yoke_core.domain import item_status_transitions
from yoke_core.domain import qa_events
from yoke_core.domain import yoke_function_actor_identity
from yoke_core.domain import yoke_function_dispatch as dispatch_module
from yoke_core.domain import yoke_function_dispatch_events as dispatch_events
from yoke_core.domain.work_claim_targets import make_item_target
from yoke_core.domain.yoke_function_dispatch import dispatch


SESSION_ID = "session-registered-surface-attribution"
ITEM_ID = 7301
LIFECYCLE_FUNCTION_ID = "lifecycle.transition.execute"
QA_RUN_COMPLETE_FUNCTION_ID = "qa.run.complete"


def _operating_actor_id(conn) -> int:
    """Seed the human actor and its org grant, as a born universe carries."""
    actor_id, _seeded = local_operating_actor.ensure_local_operating_actor(
        conn,
        label="registered-surface-attribution-human",
    )
    conn.commit()
    return int(actor_id)


def _insert_session(conn, actor_id: int) -> None:
    conn.execute(
        "INSERT INTO harness_sessions "
        "(session_id, executor, provider, model, execution_lane, workspace, "
        "offered_at, last_heartbeat, actor_id) "
        "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)",
        (
            SESSION_ID,
            "codex",
            "openai",
            "test-model",
            "ALTMAN",
            "/tmp",
            "2026-08-31T00:00:00Z",
            "2026-08-31T00:00:00Z",
            actor_id,
        ),
    )
    conn.commit()


def _hold_item_claim(conn, item_id: int, session_id: str = SESSION_ID) -> None:
    """Give *session_id* the live item claim both claim gates read."""
    target = make_item_target(item_id)
    conn.execute(
        "INSERT INTO work_claims "
        "(session_id, target_kind, scope, claim_type, claimed_at, last_heartbeat) "
        "VALUES (%s, %s, %s, 'exclusive', %s, %s)",
        (
            session_id,
            target.kind,
            target.scope_json(),
            "2026-08-31T00:00:00Z",
            "2026-08-31T00:00:00Z",
        ),
    )
    conn.commit()


def _stored_identity(conn, event_name: str):
    return conn.execute(
        "SELECT session_id, actor_id FROM events WHERE event_name = %s "
        "ORDER BY id DESC LIMIT 1",
        (event_name,),
    ).fetchone()


def _dispatch(request: FunctionCallRequest):
    """Dispatch through the real registry with only the ledger legs stubbed."""
    with (
        patch.object(dispatch_events, "emit_event"),
        patch.object(dispatch_events, "record_call", return_value=True),
        patch.object(dispatch_module, "_idempotency_lookup", return_value=None),
    ):
        return dispatch(request)


def _lifecycle_request(session_id: str) -> FunctionCallRequest:
    return FunctionCallRequest(
        function=LIFECYCLE_FUNCTION_ID,
        actor=ActorContext(session_id=session_id),
        target=TargetRef(kind="item", item_id=ITEM_ID),
        payload={
            "target_status": "reviewing-implementation",
            "source_status": "implementing",
            "reason": "implementation complete; ready for review",
            "qa_bypass": True,
        },
    )


@pytest.fixture()
def no_ambient_session(monkeypatch):
    """Make the ambient chain resolve nothing, as a sessionless caller would."""
    monkeypatch.setattr(
        events_acting_identity,
        "resolve_ambient_session_id",
        lambda: None,
    )
    monkeypatch.setattr(
        yoke_function_actor_identity,
        "resolve_ambient_session_id",
        lambda: "",
    )


def test_lifecycle_transition_stamps_stored_status_event() -> None:
    with test_database() as conn:
        actor_id = _operating_actor_id(conn)
        _insert_session(conn, actor_id)
        insert_item(conn, id=ITEM_ID, title="Attribution", status="implementing")
        _hold_item_claim(conn, ITEM_ID)

        response = _dispatch(_lifecycle_request(SESSION_ID))
        assert response.success, response.error

        row = _stored_identity(conn, "ItemStatusChanged")
        assert row is not None, "lifecycle transition wrote no ItemStatusChanged row"
        assert str(row[0]) == SESSION_ID
        assert int(row[1]) == actor_id


def test_sessionless_lifecycle_transition_is_refused_not_attributed(
    no_ambient_session,
) -> None:
    with test_database() as conn:
        _operating_actor_id(conn)
        insert_item(conn, id=ITEM_ID, title="Attribution", status="implementing")

        response = _dispatch(_lifecycle_request(""))
        assert not response.success
        assert response.error is not None
        assert response.error.code == "actor_session_missing"

        assert _stored_identity(conn, "ItemStatusChanged") is None


def test_server_internal_status_change_leaves_identity_empty(
    no_ambient_session,
) -> None:
    with test_database() as conn:
        insert_item(conn, id=ITEM_ID, title="Attribution", status="implementing")

        item_status_transitions.emit_item_status_change(
            item_id=ITEM_ID,
            from_status="implementing",
            to_status="reviewing-implementation",
            source="server-internal",
        )

        row = _stored_identity(conn, "ItemStatusChanged")
        assert row is not None
        assert str(row[0] or "") == ""
        assert row[1] is None


def _seed_open_qa_run(conn) -> tuple[int, int]:
    insert_item(conn, id=ITEM_ID, title="Attribution", status="reviewing-implementation")
    requirement = insert_qa_requirement(
        conn,
        item_id=ITEM_ID,
        qa_kind="plan_case",
        qa_phase="verification",
        blocking_mode="blocking",
        success_policy='{"id":"all-pass","params":{}}',
    )
    requirement_id = int(requirement["id"])
    run = insert_qa_run(
        conn,
        qa_requirement_id=requirement_id,
        qa_kind="plan_case",
        verdict=None,
    )
    return requirement_id, int(run["id"])


def _qa_run_complete_request(
    session_id: str,
    requirement_id: int,
    run_id: int,
) -> FunctionCallRequest:
    return FunctionCallRequest(
        function=QA_RUN_COMPLETE_FUNCTION_ID,
        actor=ActorContext(session_id=session_id),
        target=TargetRef(kind="qa_requirement", qa_requirement_id=requirement_id),
        payload={"run_id": run_id, "verdict": "pass"},
    )


def test_qa_run_complete_stamps_stored_completion_event() -> None:
    """Also guards persistence: the handler owns and closes its own
    connection, so a row read back here is one that survived that close."""
    with test_database() as conn:
        actor_id = _operating_actor_id(conn)
        _insert_session(conn, actor_id)
        requirement_id, run_id = _seed_open_qa_run(conn)
        _hold_item_claim(conn, ITEM_ID)

        response = _dispatch(
            _qa_run_complete_request(SESSION_ID, requirement_id, run_id)
        )
        assert response.success, response.error

        row = _stored_identity(conn, "QARunCompleted")
        assert row is not None, "qa.run.complete wrote no QARunCompleted row"
        assert str(row[0]) == SESSION_ID
        assert int(row[1]) == actor_id


def test_sessionless_qa_run_complete_is_refused_not_attributed(
    no_ambient_session,
) -> None:
    with test_database() as conn:
        _operating_actor_id(conn)
        requirement_id, run_id = _seed_open_qa_run(conn)

        response = _dispatch(_qa_run_complete_request("", requirement_id, run_id))
        assert not response.success
        assert response.error is not None
        assert response.error.code == "actor_session_missing"

        assert _stored_identity(conn, "QARunCompleted") is None


def test_server_internal_qa_run_event_leaves_identity_empty(
    no_ambient_session,
) -> None:
    with test_database() as conn:
        requirement_id, run_id = _seed_open_qa_run(conn)

        qa_events.emit_qa_run_event(
            conn,
            db_path=None,
            event_name="QARunCompleted",
            run_id=run_id,
            requirement_id=requirement_id,
            qa_kind="plan_case",
            verdict="pass",
        )
        conn.commit()

        row = _stored_identity(conn, "QARunCompleted")
        assert row is not None
        assert str(row[0] or "") == ""
        assert row[1] is None


def test_qa_requirement_event_survives_its_emitting_connection_close(
    no_ambient_session,
) -> None:
    """The sibling requirement-event helper must reach the ledger too.

    ``events.emit_event`` leaves a caller-supplied connection's transaction
    open, and every QA caller closes its connection right after emitting, so
    an uncommitted row is discarded. Emitting on a connection this test then
    closes reproduces exactly that shape.
    """
    with test_database() as conn:
        requirement_id, _run_id = _seed_open_qa_run(conn)

        emitting_conn = db_helpers.connect()
        try:
            qa_events.emit_qa_requirement_event(
                emitting_conn,
                db_path=None,
                event_name="QARequirementCreated",
                requirement_id=requirement_id,
                qa_kind="plan_case",
                qa_phase="verification",
            )
        finally:
            emitting_conn.close()

        row = _stored_identity(conn, "QARequirementCreated")
        assert row is not None, "requirement event did not survive the close"
