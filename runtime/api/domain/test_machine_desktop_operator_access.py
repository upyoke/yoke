"""Steering-seat assistance preserves a QA host lease; other sessions remain bound."""

from copy import deepcopy
import json
from types import SimpleNamespace

import pytest

from yoke_contracts.api.function_call import FunctionCallRequest, HandlerOutcome
from yoke_core.domain.handlers import machine_desktop_access as handler
from yoke_core.domain import db_backend
from yoke_core.domain.sessions_analytics_core import SessionError
from runtime.api.fixtures.pg_testdb import test_database


@pytest.fixture
def route(monkeypatch):
    detail = {
        "project": "example",
        "machine": "lab",
        "settings": {"desktop_route": "direct"},
        "active_lease": {
            "id": 17,
            "session_id": "holder",
            "actor_id": 2,
            "acquired_at": "2026-01-01T00:00:00Z",
            "heartbeat_at": "2026-01-01T00:01:00Z",
        },
    }
    monkeypatch.setattr(
        handler,
        "handle_get",
        lambda req: HandlerOutcome(primary_success=True, result_payload=detail),
    )
    conn = SimpleNamespace(close=lambda: None)
    monkeypatch.setattr(handler.db_helpers, "connect", lambda: conn)
    monkeypatch.setattr(handler.actors, "actor_name", lambda conn, actor: "Operator")
    monkeypatch.setattr(handler, "resolve_project_id", lambda conn, project: 1)

    def seat(conn, *, caller_session_id, project_id, action):
        if caller_session_id != "steering":
            raise SessionError(
                "steering_seat_required", f"{action} requires a live steering seat"
            )
        return {"claim_id": 9}

    monkeypatch.setattr(handler, "require_operator_seat", seat)
    return detail


def request(session_id="steering", actor_id="3"):
    return FunctionCallRequest(
        function="test_machine.desktop_access",
        request_id="desktop-assistance",
        actor={"session_id": session_id, "actor_id": actor_id},
        target={"kind": "global"},
        payload={"project": "example", "test_machine": "lab"},
    )


def test_seat_holder_access_records_actor_against_unchanged_lease(route, monkeypatch):
    before = deepcopy(route)
    events = []
    monkeypatch.setattr(
        handler,
        "emit_event",
        lambda name, **kw: events.append((name, kw)) or SimpleNamespace(ok=True),
    )
    outcome = handler.handle_desktop_access(request())
    assert outcome.primary_success
    access = outcome.result_payload["operator_access"]
    assert access["actor_id"] == "3"
    assert access["lease_id"] == 17
    assert access["steering_claim_id"] == 9
    assert access["audit_recorded"]
    assert route == before
    assert events[0][1]["session_id"] == "holder"
    assert events[0][1]["context"]["actor_id"] == "3"
    assert events[0][1]["context"]["lease_id"] == 17


def test_seat_holder_access_audit_persists_through_event_schema(route, monkeypatch):
    # Exercise the real emitter and schema, including source-type constraints.
    # The handler owns a separate connection, so inspect after it closes.
    with test_database() as conn:
        conn.execute(
            "INSERT INTO actors(id,kind,created_at) VALUES(3,'human','2026-01-01T00:00:00Z')"
        )
        conn.commit()
        monkeypatch.setattr(handler.db_helpers, "connect", db_backend.connect)
        outcome = handler.handle_desktop_access(request())
        assert outcome.result_payload["operator_access"]["audit_recorded"]
        row = conn.execute(
            "SELECT actor_id, session_id, envelope FROM events "
            "WHERE event_name=%s AND session_id=%s",
            (
                handler.EVENT_SESSION_ACTION_PERFORMED,
                route["active_lease"]["session_id"],
            ),
        ).fetchone()
        assert row["actor_id"] == 3
        assert row["session_id"] == route["active_lease"]["session_id"]
        envelope = json.loads(row["envelope"])
        assert envelope["request_id"] == request().request_id
        context = envelope["context"]
        assert context["lease_id"] == route["active_lease"]["id"]
        assert context["actor_id"] == "3"


@pytest.mark.parametrize("session_id", ["foreign", "", "holder"])
def test_access_without_a_seat_remains_bound_to_the_lease_holder(route, session_id):
    outcome = handler.handle_desktop_access(request(session_id=session_id))
    assert outcome.primary_success == (session_id == "holder")
    if session_id == "holder":
        assert "operator_access" not in outcome.result_payload
    else:
        assert outcome.error.code == "steering_seat_required"
        assert "steering seat" in outcome.error.recovery_hint


@pytest.mark.parametrize("seat_project,allowed", [(1, True), (2, False)])
def test_live_seat_must_cover_the_machine_project(monkeypatch, seat_project, allowed):
    from runtime.api.domain.test_session_message_support import message_connection
    from runtime.api.domain.test_steering_operation_authority import seat
    from yoke_core.domain import session_steering_authority

    conn = message_connection()
    seat(conn, project=seat_project)
    detail = {
        "project": "alpha",
        "machine": "lab",
        "settings": {"desktop_route": "direct"},
        "active_lease": {"id": 17, "session_id": "holder"},
    }
    monkeypatch.setattr(
        handler,
        "handle_get",
        lambda req: HandlerOutcome(primary_success=True, result_payload=detail),
    )
    monkeypatch.setattr(handler.db_helpers, "connect", lambda: conn)
    monkeypatch.setattr(handler, "resolve_project_id", lambda c, project: 1)
    monkeypatch.setattr(handler.actors, "actor_name", lambda c, actor: "Operator")
    monkeypatch.setattr(
        handler, "emit_event", lambda *a, **kw: SimpleNamespace(ok=True)
    )
    monkeypatch.setattr(
        handler,
        "require_operator_seat",
        session_steering_authority.require_operator_seat,
    )
    outcome = handler.handle_desktop_access(request(session_id="s1"))
    assert outcome.primary_success is allowed
    if not allowed:
        assert outcome.error.code == "steering_seat_required"


def test_audit_unavailable_is_explicit_and_does_not_prevent_seat_access(
    route, monkeypatch
):
    monkeypatch.setattr(
        handler,
        "emit_event",
        lambda *a, **kw: SimpleNamespace(ok=False, reason="severity_filtered"),
    )
    outcome = handler.handle_desktop_access(request())
    assert outcome.primary_success
    access = outcome.result_payload["operator_access"]
    assert not access["audit_recorded"]
    assert "severity_filtered" in access["audit_recovery"]


def test_cli_passes_only_route_to_viewer_and_reports_assistance(monkeypatch, capsys):
    from yoke_cli.commands.adapters import test_machine_desktop as cli
    from yoke_harness import desktop_access

    access = {"actor_id": "3", "actor_name": "Operator", "lease_id": 17}
    monkeypatch.setattr(cli, "ensure_handlers_loaded", lambda: None)
    monkeypatch.setattr(
        cli,
        "call_dispatcher",
        lambda **kw: SimpleNamespace(
            success=True,
            result={
                "project": "example",
                "machine": "lab",
                "settings": {},
                "operator_access": access,
            },
        ),
    )
    calls = []
    monkeypatch.setattr(
        desktop_access,
        "open_desktop_access",
        lambda **kw: calls.append(kw) or {"address": "rdp://localhost"},
    )
    assert (
        cli.test_machine_desktop_access(
            ["--project", "example", "--test-machine", "lab", "--view"]
        )
        == 0
    )
    assert calls == [
        {"project": "example", "machine": "lab", "settings": {}, "view": True}
    ]
    output = capsys.readouterr()
    assert "Operator" in output.err and "lease unchanged" in output.err
    assert '"operator_access"' in output.out
