"""Domain callers depend on contracts rather than service-client adapters."""

from __future__ import annotations

import ast
from pathlib import Path
from types import SimpleNamespace

from yoke_contracts.api.function_call import ActorContext, FunctionCallResponse, TargetRef
from yoke_contracts.runtime_ports.structured_dispatch import get_structured_dispatch


def test_domain_does_not_import_service_clients():
    root = Path(__file__).resolve().parents[3]
    core = root / "packages/yoke-core/src/yoke_core"
    paths = [*core.glob("*.py"), *(core / "board").rglob("*.py")]
    paths.extend(
        path for path in (core / "domain").rglob("*.py")
        if "handlers" not in path.relative_to(core / "domain").parts
    )
    violations = []
    for path in paths:
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.ImportFrom):
                modules = [node.module or ""]
                modules.extend(f"{node.module}.{alias.name}" for alias in node.names)
            elif isinstance(node, ast.Import):
                modules = [alias.name for alias in node.names]
            else:
                continue
            if any(module.startswith("yoke_core.api.service_client") for module in modules):
                violations.append(f"{path.relative_to(core)}:{node.lineno}")
    assert violations == []


def test_function_call_interface_retains_the_transport_provider():
    from yoke_core.api import service_client_structured_api_adapter as adapter

    port = get_structured_dispatch()
    assert port is adapter
    assert port.build_actor is adapter.build_actor
    assert port.emit_response is adapter.emit_response


def test_domain_relay_uses_an_independent_function_call_provider(monkeypatch):
    from yoke_core.domain import control_plane_transport

    seen = {}

    def call(**kwargs):
        seen.update(kwargs)
        return FunctionCallResponse(
            success=True, function=kwargs["function_id"], version="v1",
            request_id="request", result={"served": True},
        )

    monkeypatch.setattr(
        control_plane_transport, "get_structured_dispatch",
        lambda: SimpleNamespace(call_dispatcher=call),
    )
    target = TargetRef(kind="global")
    assert control_plane_transport.relay("example.read", {"key": "value"}, target, env="remote") == {"served": True}
    assert seen == {
        "function_id": "example.read", "payload": {"key": "value"},
        "target": target, "relay_env": "remote",
    }


def test_function_call_interface_preserves_local_dispatch(monkeypatch):
    from yoke_core.api import service_client_structured_api_adapter as adapter
    from yoke_cli.transport import https

    def unexpected_transport():
        raise AssertionError("a local call must not resolve HTTPS")

    monkeypatch.setattr(https, "resolve_https_connection", unexpected_transport)
    requests = []

    def dispatch(request):
        requests.append(request)
        return FunctionCallResponse(
            success=True, function=request.function, version=request.version,
            request_id=request.request_id, result={},
        )

    monkeypatch.setattr(adapter, "dispatch", dispatch)
    actor = ActorContext(actor_id="actor", session_id="session")
    response = get_structured_dispatch().call_dispatcher(
        function_id="example.read", target=TargetRef(kind="global"),
        actor=actor, request_id="stable-request", local_only=True,
    )
    assert response.success
    assert requests[0].actor == actor
    assert requests[0].request_id == "stable-request"
