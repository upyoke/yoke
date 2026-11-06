# ruff: noqa: F401, E402
"""Shared setup for tests in this directory."""

from contextlib import nullcontext

import json

from types import SimpleNamespace

import pytest

from runtime.api.domain.machine_authorization_codes_test_support import (
    conn as _conn_fixture,
    pending as start,
)

from yoke_cli.commands import _helpers, connect, registry

from yoke_cli.commands.adapters import machine_admission as commands

from yoke_cli.commands.adapters.admission_floor_recovery import ADMISSION_FLOOR_RECOVERY

from yoke_cli.config import local_reachability, hosted_machine_authorization as hosted

from yoke_cli.transport import dispatcher, function_version_skew, https

from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallResponse,
    FunctionError,
    TargetRef,
)

from yoke_core.domain.handlers import _register_inbox, machine_authorization as handlers

from yoke_core.domain.terminal_reachable_functions import TERMINAL_RECIPES

VIEWER = {"actor_id": 1, "name": "Pat"}

DETAIL = {"code": "K7F2", "machine": "Pat's laptop", "viewer": VIEWER}


@pytest.fixture()
def transport(monkeypatch):
    state = SimpleNamespace(calls=[], missing=None, mode="self-host", handler=None)
    monkeypatch.setattr(_helpers, "ensure_handlers_loaded", lambda: None)
    monkeypatch.setattr(commands, "ensure_handlers_loaded", lambda: None)
    monkeypatch.setattr(dispatcher, "_resolve_session_id", lambda: "")
    monkeypatch.delenv("YOKE_ACTOR_ID", raising=False)
    monkeypatch.setattr(
        https,
        "resolve_https_connection",
        lambda: https.HttpsConnection("https://team.example", "test-token", env="team"),
    )
    monkeypatch.setattr(
        function_version_skew, "local_handshake_version", lambda: "2.0.0"
    )
    monkeypatch.setattr(
        dispatcher, "warn_if_behind_active_connection", lambda **kw: None
    )

    def relay(request, connection, *, handshake, **kwargs):
        handshake.engine_version = "1.0.0"
        state.calls.append(request)
        if state.missing == request.function:
            return FunctionCallResponse(
                success=False,
                function=request.function,
                version=request.version,
                request_id=request.request_id,
                error=FunctionError(
                    code="function_not_registered",
                    message="function id is not registered",
                ),
            )
        if state.handler:
            outcome = state.handler(request)
            return FunctionCallResponse(
                success=outcome.primary_success,
                function=request.function,
                version=request.version,
                request_id=request.request_id,
                result=outcome.result_payload,
                error=outcome.error,
            )
        if request.function.endswith(".pending"):
            result = {
                "viewer": VIEWER,
                "mode": state.mode,
                "requests": [
                    {
                        **DETAIL,
                        "requested_by": None,
                        "expires_at": "2030-01-01T00:00:00Z",
                    }
                ],
            }
        elif request.function.endswith(".get"):
            result = {"authorization": DETAIL}
        else:
            result = {"authorization": {"decision": request.payload["action"]}}
        return FunctionCallResponse(
            success=True,
            function=request.function,
            version=request.version,
            request_id=request.request_id,
            result=result,
        )

    monkeypatch.setattr(https, "relay_https", relay)
    return state
