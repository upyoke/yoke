# ruff: noqa: F401, E402
"""Shared setup for tests in this directory."""

from __future__ import annotations

from yoke_cli.transport import dispatcher as yoke_dispatcher

from yoke_cli.transport import function_version_skew

from yoke_cli.transport import https as yoke_transport

from yoke_cli.transport.function_version_skew import (
    SKEW_ERROR_CODE,
    UNKNOWN_VERSION,
    skew_error,
)

from yoke_cli.transport.https import HttpsConnection

from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    FunctionCallResponse,
    FunctionError,
    TargetRef,
)

SERVED_LOCALLY = "items.get.run"


def _not_registered(request, _connection, **_kwargs) -> FunctionCallResponse:
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


def _relay_returning(response_factory, server_version: str):
    def relay(request, connection, *, handshake=None, **_kwargs):
        if handshake is not None:
            handshake.engine_version = server_version
        return response_factory(request, connection)

    return relay


def _dispatch_over_https(
    monkeypatch,
    *,
    server_version: str,
    client_version: str,
    function_id: str = SERVED_LOCALLY,
    env: str = "prod",
    relay=None,
) -> FunctionCallResponse:
    monkeypatch.setattr(
        yoke_transport,
        "resolve_https_connection",
        lambda path=None: HttpsConnection("https://api.example", "tok", env=env),
    )
    monkeypatch.setattr(
        yoke_transport,
        "relay_https",
        relay or _relay_returning(_not_registered, server_version),
    )
    monkeypatch.setattr(
        function_version_skew, "local_handshake_version", lambda: client_version
    )
    return yoke_dispatcher.call_dispatcher(
        function_id=function_id,
        target=TargetRef(kind="global"),
        actor=ActorContext(actor_id="a", session_id="s1"),
    )
