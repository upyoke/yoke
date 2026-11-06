# ruff: noqa: F401, E402
"""Shared setup for tests in this directory."""

from __future__ import annotations

import json

from datetime import datetime, timezone

import pytest

from runtime.api.fixtures.backlog import insert_item

from runtime.api.sessions_test_support import _register

from yoke_contracts.api.function_call import FunctionCallRequest

from yoke_contracts.session_control.liveness import LIVENESS_ENDED, LIVENESS_STATES

from yoke_core.domain.handlers.session_termination import handle_session_terminate

from yoke_core.domain.session_control_schema import create_session_control_tables

from yoke_core.domain.session_staleness import session_liveness

from yoke_core.domain.session_termination import (
    terminate_cancelled_launch_session,
    terminate_session,
)

from yoke_core.domain.sessions import SessionError, claim_work

from yoke_core.domain.sessions_list_read import list_sessions

from yoke_core.domain.steering_claims import acquire as acquire_steering

from yoke_core.domain.work_claim_targets import make_steering_target

NOW = "2026-08-26T12:00:00Z"

MACHINE_ID = "11111111-1111-4111-8111-111111111111"


@pytest.fixture(autouse=True)
def _termination_schema_and_events(conn, monkeypatch):
    create_session_control_tables(conn)
    conn.execute(
        "INSERT INTO actors (id,kind,created_at) VALUES "
        "(41,'human',%s),(42,'human',%s),(43,'human',%s)",
        (NOW, NOW, NOW),
    )
    conn.commit()
    events: list[tuple[str, dict]] = []
    monkeypatch.setattr(
        "yoke_core.domain.session_termination.emit_session_terminated",
        lambda session_id, context: events.append((session_id, context)),
    )
    monkeypatch.setattr(
        "yoke_core.domain.sessions_render_end.emit_release_claims_branch_event",
        lambda *args, **kwargs: None,
    )
    monkeypatch.setattr(
        "yoke_core.domain.sessions_render_end._sa._emit_session_event",
        lambda *args, **kwargs: None,
    )
    return events


def _register_operator_and_target(conn, *, target="worker") -> None:
    _register(
        conn,
        session_id="operator",
        actor_id=41,
        mode="wait",
    )
    acquire_steering(
        conn, session_id="operator", project_id=1, reason="terminate session"
    )
    _register(
        conn,
        session_id=target,
        actor_id=42,
        machine_id=MACHINE_ID,
        native_thread_id="native-worker-1",
    )


def _add_target_claim(conn, *, session_id="worker", item_id=900) -> None:
    insert_item(conn, id=item_id, workflow_id="issue")
    claim_work(conn, session_id=session_id, item_id=item_id)


def _add_open_message(conn, *, session_id="worker", state="injected") -> None:
    conn.execute(
        "INSERT INTO session_messages "
        "(message_id,sender_actor_id,sender_session_id,body,body_sha256,"
        "selector_snapshot,created_at,expires_at) VALUES "
        "('message-1',41,'operator','finish','sha256:body','{}',%s,"
        "'2026-08-27T12:00:00Z')",
        (NOW,),
    )
    conn.execute(
        "INSERT INTO session_message_recipients "
        "(message_id,session_id,project_id,resolution_evidence,routing_snapshot,"
        "state,created_at,wake_after,injection_lease_id,injection_leased_at,"
        "injection_lease_expires_at) VALUES "
        "('message-1',%s,1,'{}','{}',%s,%s,%s,'lease-1',%s,"
        "'2026-08-27T12:00:00Z')",
        (session_id, state, NOW, NOW, NOW),
    )
    conn.execute(
        "INSERT INTO session_message_attempts "
        "(attempt_id,message_id,target_session_id,attempt_kind,lease_id,started_at) "
        "VALUES ('attempt-1','message-1',%s,'hook','lease-1',%s)",
        (session_id, NOW),
    )
    conn.commit()


def _terminate(conn, **overrides):
    arguments = {
        "target_session_id": "worker",
        "actor_id": 41,
        "caller_session_id": "operator",
        "reason": "worker completed",
    }
    arguments.update(overrides)
    return terminate_session(conn, **arguments)


class _HandlerConnection:
    """Expose the fixture connection to the handler without closing it."""

    def __init__(self, conn) -> None:
        self._conn = conn
        self.committed = False

    def commit(self) -> None:
        self._conn.commit()
        self.committed = True

    def close(self) -> None:
        return None

    def __getattr__(self, name):
        return getattr(self._conn, name)
