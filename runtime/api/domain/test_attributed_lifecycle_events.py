"""Stored-row coverage for acting identity on lifecycle and QA events."""

from __future__ import annotations

from unittest.mock import patch

from pydantic import BaseModel

from runtime.api.fixtures.pg_testdb import test_database
from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    HandlerOutcome,
    TargetRef,
)
from yoke_core.domain import events
from yoke_core.domain import events_acting_identity
from yoke_core.domain import actors
from yoke_core.domain import yoke_function_dispatch as dispatch_module
from yoke_core.domain import yoke_function_dispatch_events as dispatch_events
from yoke_core.domain.auth_context import StandardAuthContext
from yoke_core.domain.yoke_function_dispatch import dispatch
from yoke_core.domain.yoke_function_registry import (
    register,
    reset_registry_for_tests,
)


SESSION_ID = "session-attributed-events"
FUNCTION_ID = "sessions.touch"
EVENT_NAMES = frozenset(
    {
        "ItemStatusChanged",
        "QARunCaptured",
        "QARunCompleted",
    }
)


class _Request(BaseModel):
    pass


class _Response(BaseModel):
    pass


def _actor_ids(conn) -> tuple[int, int]:
    system_actor_id, human_actor_id = actors.seed_canonical_actors(
        conn,
        local_human_label="attribution-test-human",
    )
    return human_actor_id, system_actor_id


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
            "2026-08-28T00:00:00Z",
            "2026-08-28T00:00:00Z",
            actor_id,
        ),
    )
    conn.commit()


def _register_emitter(conn, wrong_actor_id: int) -> None:
    def emit_from_handler(_request: FunctionCallRequest) -> HandlerOutcome:
        for event_name in EVENT_NAMES:
            result = events.emit_event(
                event_name,
                event_kind="lifecycle",
                event_type="attribution_test",
                session_id="caller-supplied-session",
                auth_context=StandardAuthContext(actor_id=wrong_actor_id),
                conn=conn,
            )
            assert result.ok, result.reason
        conn.commit()
        return HandlerOutcome(result_payload={}, primary_success=True)

    register(
        FUNCTION_ID,
        emit_from_handler,
        _Request,
        _Response,
        stability="stable",
        owner_module=__name__,
        target_kinds=["global"],
        side_effects=["emit_event"],
        emitted_event_names=sorted(EVENT_NAMES),
        guardrails=[],
        adapter_status="live",
    )


def test_dispatch_stamps_stored_rows_from_real_session() -> None:
    assert events_acting_identity.ACTING_IDENTITY_EVENT_NAMES == EVENT_NAMES
    with test_database() as conn:
        human_actor_id, system_actor_id = _actor_ids(conn)
        _insert_session(conn, human_actor_id)
        reset_registry_for_tests()
        try:
            _register_emitter(conn, system_actor_id)
            request = FunctionCallRequest(
                function=FUNCTION_ID,
                actor=ActorContext(session_id=SESSION_ID),
                target=TargetRef(kind="global"),
            )
            with (
                patch.object(dispatch_module, "_ensure_handlers_registered"),
                patch.object(dispatch_events, "emit_event"),
                patch.object(dispatch_events, "record_call", return_value=True),
                patch.object(dispatch_module, "_idempotency_lookup", return_value=None),
            ):
                response = dispatch(request)
            assert response.success, response.error

            rows = conn.execute(
                "SELECT event_name, session_id, actor_id FROM events "
                "WHERE event_name = ANY(%s) ORDER BY event_name",
                (list(EVENT_NAMES),),
            ).fetchall()
            assert {str(row[0]) for row in rows} == EVENT_NAMES
            assert {str(row[1]) for row in rows} == {SESSION_ID}
            assert {int(row[2]) for row in rows} == {human_actor_id}
        finally:
            reset_registry_for_tests()


def test_sessionless_events_leave_identity_empty(monkeypatch) -> None:
    monkeypatch.setattr(
        events_acting_identity,
        "resolve_ambient_session_id",
        lambda: None,
    )
    with test_database() as conn:
        human_actor_id, _system_actor_id = _actor_ids(conn)
        for event_name in EVENT_NAMES:
            result = events.emit_event(
                event_name,
                event_kind="lifecycle",
                event_type="attribution_test",
                session_id="caller-supplied-session",
                auth_context=StandardAuthContext(actor_id=human_actor_id),
                conn=conn,
            )
            assert result.ok, result.reason
        rows = conn.execute(
            "SELECT session_id, actor_id FROM events WHERE event_name = ANY(%s)",
            (list(EVENT_NAMES),),
        ).fetchall()
        assert len(rows) == len(EVENT_NAMES)
        assert {str(row[0] or "") for row in rows} == {""}
        assert {row[1] for row in rows} == {None}


def test_empty_bound_identity_falls_through_to_ambient(monkeypatch) -> None:
    monkeypatch.setattr(
        events_acting_identity,
        "resolve_ambient_session_id",
        lambda: SESSION_ID,
    )
    with test_database() as conn:
        human_actor_id, _system_actor_id = _actor_ids(conn)
        _insert_session(conn, human_actor_id)
        with events_acting_identity.acting_event_identity(
            session_id="",
            actor_id=None,
        ):
            result = events.emit_event(
                "ItemStatusChanged",
                event_kind="lifecycle",
                event_type="attribution_test",
                session_id="caller-supplied-session",
                auth_context=StandardAuthContext(actor_id=human_actor_id),
                conn=conn,
            )
            assert result.ok, result.reason
        row = conn.execute(
            "SELECT session_id, actor_id FROM events WHERE event_name = %s",
            ("ItemStatusChanged",),
        ).fetchone()
        assert row is not None
        assert str(row[0]) == SESSION_ID
        assert int(row[1]) == human_actor_id
