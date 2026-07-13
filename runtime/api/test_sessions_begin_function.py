"""Tests for the transport-keyed ``sessions.begin`` function surface.

Covers three layers of the session-establishment path that ``/yoke do``
bootstrap depends on:

* The ``sessions.begin`` registration/authz/adapter coherence (a new
  function id must ship its handler, its explicit authorization scope, its
  CLI adapter, and its inventory rows).
* ``handle_begin`` request parsing + error mapping (unit, with the shared
  ``begin_session`` core mocked) and ``begin_session`` end-to-end
  registration + idempotency against a real backend.
* The ``yoke sessions begin`` CLI adapter's connection-keyed routing: an
  https active connection relays to the server (the fix for prod-over-https
  bootstrap), a local connection dispatches in-process.
"""

from __future__ import annotations

import pytest

from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    FunctionCallResponse,
    TargetRef,
)
from runtime.api.test_constants import TEST_MODEL_ID
from runtime.api.test_service_client_sessions_helpers import (
    session_offer_db,  # noqa: F401 — re-exported fixture
)


def _valid_payload() -> dict:
    return {
        "executor": "claude-code",
        "provider": "anthropic",
        "model": TEST_MODEL_ID,
        "workspace": "/ws",
        "project_id": 1,
    }


def _request(session_id: str, payload: dict) -> FunctionCallRequest:
    return FunctionCallRequest(
        function="sessions.begin",
        actor=ActorContext(session_id=session_id),
        target=TargetRef(kind="global"),
        request_id="req-begin",
        payload=payload,
    )


class TestRegistrationCoherence:
    """The new function id must be registered, classified, and wrapped."""

    def test_registered_without_ambient_session(self):
        from yoke_core.domain.handlers.__init_register__ import (
            register_all_handlers,
        )
        from yoke_core.domain.yoke_function_registry import lookup

        register_all_handlers()
        entry = lookup("sessions.begin")
        assert entry is not None
        # A session-creation call cannot require a pre-existing session.
        assert entry.ambient_session_required is False

    def test_authz_scope_is_not_fail_closed(self):
        from yoke_core.domain.function_authz_scope import (
            DENY,
            classify,
            permission_key_for,
        )
        from yoke_core.domain.handlers.__init_register__ import (
            register_all_handlers,
        )
        from yoke_core.domain.yoke_function_registry import lookup

        register_all_handlers()
        entry = lookup("sessions.begin")
        spec = classify(
            "sessions.begin",
            side_effects=bool(entry.side_effects),
            project_permission=permission_key_for(entry),
        )
        assert spec.scope != DENY

    def test_cli_adapter_and_inventory_present(self):
        from yoke_cli import operation_inventory as inv
        from yoke_cli.commands.registry import SUBCOMMAND_REGISTRY

        assert ("sessions", "begin") in SUBCOMMAND_REGISTRY
        function_id, _adapter = SUBCOMMAND_REGISTRY[("sessions", "begin")]
        assert function_id == "sessions.begin"
        entry = inv.lookup("yoke sessions begin")
        assert entry is not None
        assert entry.status == inv.WRAPPED


class TestHandleBeginUnit:
    """``handle_begin`` request parsing and error mapping (core mocked)."""

    def test_missing_session_id_is_rejected(self):
        from yoke_core.domain.handlers.sessions_begin import handle_begin

        out = handle_begin(_request("", _valid_payload()))
        assert out.primary_success is False
        assert out.error is not None
        assert out.error.code == "session_required"

    def test_invalid_payload_is_rejected(self):
        from yoke_core.domain.handlers.sessions_begin import handle_begin

        bad = _valid_payload()
        del bad["project_id"]
        out = handle_begin(_request("sid", bad))
        assert out.primary_success is False
        assert out.error is not None
        assert out.error.code == "payload_invalid"

    def test_success_returns_core_result(self, monkeypatch):
        import yoke_core.api.service_client_sessions_lifecycle_begin as begin_mod
        from yoke_core.domain.handlers import sessions_begin as so

        class _DummyConn:
            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

        captured = {}

        def fake_begin(conn, **kwargs):
            captured.update(kwargs)
            return {"success": True, "session": {"session_id": kwargs["session_id"]}}

        monkeypatch.setattr(so, "_connect_rw", lambda: _DummyConn())
        monkeypatch.setattr(begin_mod, "begin_session", fake_begin)
        out = so.handle_begin(_request("sid-happy", _valid_payload()))
        assert out.error is None
        assert out.result_payload == {
            "success": True,
            "session": {"session_id": "sid-happy"},
        }
        # session id is taken from the actor, not the payload.
        assert captured["session_id"] == "sid-happy"
        assert captured["project_id"] == 1

    def test_session_error_is_mapped(self, monkeypatch):
        import yoke_core.api.service_client_sessions_lifecycle_begin as begin_mod
        from yoke_core.domain.handlers import sessions_begin as so
        from yoke_core.domain.sessions import SessionError

        class _DummyConn:
            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

        def fake_begin(conn, **kwargs):
            raise SessionError("PROJECT_UNKNOWN", "no such project")

        monkeypatch.setattr(so, "_connect_rw", lambda: _DummyConn())
        monkeypatch.setattr(begin_mod, "begin_session", fake_begin)
        out = so.handle_begin(_request("sid", _valid_payload()))
        assert out.primary_success is False
        assert out.error is not None
        assert out.error.code == "project_unknown"


class TestBeginSessionIntegration:
    """``begin_session`` registers a real row and is idempotent."""

    def test_registers_and_is_idempotent(self, session_offer_db):
        from yoke_core.api.service_client_sessions_lifecycle_begin import (
            begin_session,
        )
        from yoke_core.domain import db_backend

        conn = db_backend.connect()
        try:
            first = begin_session(
                conn,
                session_id="sid-local",
                executor="claude-code",
                provider="anthropic",
                model=TEST_MODEL_ID,
                workspace=session_offer_db["tmp_dir"],
                project_id=1,
            )
            assert first["success"] is True
            assert "session" in first

            second = begin_session(
                conn,
                session_id="sid-local",
                executor="claude-code",
                provider="anthropic",
                model=TEST_MODEL_ID,
                workspace=session_offer_db["tmp_dir"],
                project_id=1,
            )
            assert second["success"] is True
            assert second.get("already_registered") is True

            row = conn.execute(
                "SELECT session_id FROM harness_sessions WHERE session_id = %s",
                ("sid-local",),
            ).fetchone()
            assert row is not None
        finally:
            conn.close()


def _ok_response(request: FunctionCallRequest) -> FunctionCallResponse:
    return FunctionCallResponse(
        success=True,
        function=request.function,
        version="v1",
        request_id=request.request_id,
        result={"success": True, "session": {"session_id": request.actor.session_id}},
    )


_BEGIN_ARGS = [
    "--executor", "claude-code",
    "--provider", "anthropic",
    "--model", TEST_MODEL_ID,
    "--workspace", "/ws",
    "--project", "1",
    "--session-id", "sid-cli",
    "--json",
]


class TestAdapterTransportRouting:
    """The adapter's connection-keyed routing — https relay vs local."""

    def test_relays_over_https_when_connection_active(self, monkeypatch):
        import yoke_cli.commands._helpers as helpers_mod
        from yoke_cli.commands.adapters.sessions import sessions_begin
        from yoke_cli.transport import https as https_mod
        from yoke_cli.transport.https import HttpsConnection

        monkeypatch.setattr(helpers_mod, "ensure_handlers_loaded", lambda: None)
        conn = HttpsConnection(
            api_url="https://api.example", token="tok", env="prod",
        )
        monkeypatch.setattr(
            https_mod, "resolve_https_connection", lambda: conn,
        )
        captured = {}

        def fake_relay(request, connection, **kwargs):
            captured["request"] = request
            captured["connection"] = connection
            return _ok_response(request)

        monkeypatch.setattr(https_mod, "relay_https", fake_relay)
        rc = sessions_begin(list(_BEGIN_ARGS))
        assert rc == 0
        request = captured["request"]
        assert request.function == "sessions.begin"
        assert request.actor.session_id == "sid-cli"
        assert request.payload["project_id"] == 1
        assert request.payload["executor"] == "claude-code"
        assert captured["connection"] is conn

    def test_dispatches_locally_when_no_https(self, monkeypatch):
        import yoke_cli.commands._helpers as helpers_mod
        import yoke_cli.transport.dispatcher as dispatcher_mod
        from yoke_cli.commands.adapters.sessions import sessions_begin
        from yoke_cli.transport import https as https_mod

        monkeypatch.setattr(helpers_mod, "ensure_handlers_loaded", lambda: None)
        monkeypatch.setattr(
            https_mod, "resolve_https_connection", lambda: None,
        )

        def forbidden_relay(*args, **kwargs):
            raise AssertionError("relay_https must not run on the local path")

        monkeypatch.setattr(https_mod, "relay_https", forbidden_relay)
        captured = {}

        def fake_local(request, local_dispatch):
            captured["request"] = request
            return _ok_response(request)

        monkeypatch.setattr(dispatcher_mod, "_call_local", fake_local)
        rc = sessions_begin(list(_BEGIN_ARGS))
        assert rc == 0
        request = captured["request"]
        assert request.function == "sessions.begin"
        assert request.payload["project_id"] == 1
        assert request.actor.session_id == "sid-cli"

    def test_unresolvable_project_errors_before_dispatch(self, monkeypatch):
        from yoke_cli.config import machine_config
        from yoke_cli.commands.adapters.sessions import sessions_begin

        monkeypatch.setattr(machine_config, "project_id", lambda path: None)
        rc = sessions_begin([
            "--executor", "claude-code",
            "--provider", "anthropic",
            "--model", TEST_MODEL_ID,
            "--workspace", "/unmapped",
        ])
        assert rc == 2
