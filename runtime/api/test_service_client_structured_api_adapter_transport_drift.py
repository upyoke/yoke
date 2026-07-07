"""HTTPS function-drift hints for the CLI dispatch adapter."""

from __future__ import annotations

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


def test_https_function_not_registered_names_deploy_and_local_env(
    monkeypatch,
) -> None:
    import yoke_cli.transport.https as transport
    from yoke_core.domain import machine_config

    monkeypatch.setattr(
        transport,
        "resolve_https_connection",
        lambda path=None: HttpsConnection("https://api.example", "tok"),
    )
    monkeypatch.setattr(transport, "relay_https", _missing_response)
    monkeypatch.setattr(machine_config, "active_env", lambda path=None: "prod")
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
    hint = response.error.recovery_hint or ""
    assert "active HTTPS env 'prod' does not serve `strategy.doc.create`" in hint
    assert "Deploy or update the Yoke API" in hint
    assert "yoke --env prod-db-admin strategy doc create" in hint


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
    assert "Deploy or update the Yoke API" not in (
        response.error.recovery_hint or ""
    )
