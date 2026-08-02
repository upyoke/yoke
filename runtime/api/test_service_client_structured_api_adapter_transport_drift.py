"""HTTPS function-drift hints for the CLI dispatch adapter."""

from __future__ import annotations

from yoke_cli.transport.function_version_skew import SKEW_ERROR_CODE
from yoke_cli.transport.https import HttpsConnection
from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallResponse,
    FunctionError,
    TargetRef,
)
from yoke_core.api.service_client_structured_api_adapter import call_dispatcher


def _missing_response(request, _connection, **_kwargs) -> FunctionCallResponse:
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


def test_https_function_not_registered_adds_the_local_env_rerun(
    monkeypatch,
) -> None:
    import yoke_cli.transport.https as transport
    from yoke_core.domain import machine_config

    monkeypatch.setattr(
        transport,
        "resolve_https_connection",
        lambda path=None: HttpsConnection("https://api.example", "tok", env="prod"),
    )
    monkeypatch.setattr(transport, "relay_https", _missing_response)
    monkeypatch.setattr(
        machine_config,
        "load_config",
        lambda path=None: {
            "connections": {
                "prod": {"transport": "https"},
                "prod-db-admin": {"transport": "local-postgres"},
            }
        },
    )

    response = call_dispatcher(
        function_id="strategy.doc.create",
        target=TargetRef(kind="global"),
        actor=ActorContext(actor_id="t", session_id=""),
    )

    assert response.success is False
    assert response.error is not None
    assert response.error.code == SKEW_ERROR_CODE
    assert "env 'prod' does not serve function 'strategy.doc.create'" in (
        response.error.message
    )
    assert "yoke --env prod-db-admin strategy doc create" in (
        response.error.recovery_hint or ""
    )


def test_unknown_local_function_keeps_original_server_error(monkeypatch) -> None:
    import yoke_cli.transport.https as transport

    monkeypatch.setattr(
        transport,
        "resolve_https_connection",
        lambda path=None: HttpsConnection("https://api.example", "tok"),
    )
    monkeypatch.setattr(transport, "relay_https", _missing_response)

    response = call_dispatcher(
        function_id="missing.family.op",
        target=TargetRef(kind="global"),
        actor=ActorContext(actor_id="t", session_id=""),
    )

    assert response.error is not None
    assert response.error.code == "function_not_registered"
