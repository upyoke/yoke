"""Envelope-construction contract for the CLI dispatch adapter.

Sibling of ``test_service_client_structured_api_adapter.py`` (350-cap
split): pins ``build_request``'s request_id minting — every CLI envelope
carries one so transport-level retries replay-dedup; the dispatcher
ledgers only side-effecting calls (see the dispatcher idempotency suite).
"""

from __future__ import annotations

from yoke_contracts.api.function_call import ActorContext, TargetRef
from yoke_core.api.service_client_structured_api_adapter import build_request


def _kwargs() -> dict:
    return dict(
        function_id="cli_parity.test.echo",
        target=TargetRef(kind="global"),
        actor=ActorContext(actor_id="t", session_id=""),
    )


def test_build_request_mints_request_id() -> None:
    minted = build_request(**_kwargs())
    assert minted.request_id
    assert minted.request_id != build_request(**_kwargs()).request_id


def test_build_request_respects_explicit_request_id() -> None:
    explicit = build_request(**_kwargs(), request_id="r-explicit")
    assert explicit.request_id == "r-explicit"


def test_local_only_never_resolves_https_transport(monkeypatch) -> None:
    """``local_only=True`` pins in-process dispatch — client-local
    operations (repo-tree renderers) must not relay server-side
    (13011/13014)."""
    import yoke_cli.transport.https as transport
    import yoke_core.api.service_client_structured_api_adapter as adapter

    def _explode():
        raise AssertionError("local_only call resolved the https transport")

    monkeypatch.setattr(transport, "resolve_https_connection", _explode)
    seen: dict = {}

    def _fake_dispatch(request):
        seen["function"] = request.function
        from yoke_contracts.api.function_call import (
            FunctionCallResponse,
        )
        return FunctionCallResponse(
            success=True,
            function=request.function,
            version=request.version,
            request_id=request.request_id,
            result={},
        )

    monkeypatch.setattr(adapter, "dispatch", _fake_dispatch)
    response = adapter.call_dispatcher(**_kwargs(), local_only=True)
    assert response.success
    assert seen["function"] == "cli_parity.test.echo"
