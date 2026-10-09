"""Human assistance preserves a QA host lease; harness sessions remain bound."""

from copy import deepcopy
from types import SimpleNamespace

import pytest

from yoke_contracts.api.function_call import FunctionCallRequest, HandlerOutcome
from yoke_core.domain.handlers import machine_desktop_access as handler


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
    monkeypatch.setattr(
        handler.actors, "is_human_actor", lambda conn, actor: actor == 3
    )
    monkeypatch.setattr(handler.actors, "actor_name", lambda conn, actor: "Operator")
    monkeypatch.setattr(handler, "bind_operating_actor", lambda req: req)
    return detail


def request(session_id="", actor_id="3"):
    return FunctionCallRequest(
        function="test_machine.desktop_access",
        request_id="desktop-assistance",
        actor={"session_id": session_id, "actor_id": actor_id},
        target={"kind": "global"},
        payload={"project": "example", "machine": "lab"},
    )


def test_human_access_records_actor_against_unchanged_lease(route, monkeypatch):
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
    assert access["audit_recorded"]
    assert route == before
    assert events[0][1]["session_id"] == "holder"
    assert events[0][1]["context"]["actor_id"] == "3"
    assert events[0][1]["context"]["lease_id"] == 17


@pytest.mark.parametrize("session_id", ["foreign", "holder"])
def test_harness_access_remains_bound_to_session_even_for_human_actor(
    route, session_id
):
    outcome = handler.handle_desktop_access(request(session_id=session_id))
    assert outcome.primary_success == (session_id == "holder")
    if session_id == "foreign":
        assert outcome.error.code == "test_machine_leased"
        assert "plain terminal" in outcome.error.recovery_hint
    else:
        assert "operator_access" not in outcome.result_payload


@pytest.mark.parametrize("actor_id", [None, "1", "unbound"])
def test_sessionless_unattributed_or_system_caller_cannot_assist(route, actor_id):
    outcome = handler.handle_desktop_access(request(actor_id=actor_id))
    assert outcome.error.code == "desktop_operator_identity_required"


def test_local_terminal_binds_its_operating_human(route, monkeypatch):
    monkeypatch.setattr(handler, "bind_operating_actor", lambda req: request())
    monkeypatch.setattr(
        handler, "emit_event", lambda *a, **kw: SimpleNamespace(ok=True)
    )
    outcome = handler.handle_desktop_access(request(actor_id=None))
    assert outcome.primary_success
    assert outcome.result_payload["operator_access"]["actor_id"] == "3"


def test_audit_unavailable_is_explicit_and_does_not_prevent_human_access(
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
            ["--project", "example", "--machine", "lab", "--view"]
        )
        == 0
    )
    assert calls == [
        {"project": "example", "machine": "lab", "settings": {}, "view": True}
    ]
    output = capsys.readouterr()
    assert "Operator" in output.err and "lease unchanged" in output.err
    assert '"operator_access"' in output.out
