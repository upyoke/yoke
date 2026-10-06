"""Payload validation and binding failures at the Local browser boundary."""

import pytest

from runtime.api.universe_ui_server_test_support import _TOKEN, ui_client as ui_client
from yoke_contracts.api.function_call import FunctionCallResponse
from yoke_core.domain import yoke_function_dispatch
from yoke_core.ui import function_proxy, proxy_transport


@pytest.mark.parametrize(
    "payload", ["invalid", 1, ["invalid"], [["open", True]], [], "", 0, False, None]
)
@pytest.mark.parametrize(
    "function_id", ["organizations.get", "projects.list", "items.create"]
)
@pytest.mark.parametrize("relayed", [False, True])
def test_non_object_payload_is_refused_before_dispatch(
    ui_client, monkeypatch, payload, function_id, relayed
):
    def unexpected_dispatch(*args, **kwargs):
        pytest.fail("a malformed browser payload must not reach dispatch or relay")

    monkeypatch.setattr(yoke_function_dispatch, "dispatch", unexpected_dispatch)
    monkeypatch.setattr(proxy_transport, "relay_call", unexpected_dispatch)
    monkeypatch.setattr(proxy_transport, "relays_to_server", lambda: relayed)
    response = ui_client.post(
        f"/api/functions/call?token={_TOKEN}",
        json={
            "function": function_id,
            "request_id": "payload-proof",
            "payload": payload,
        },
    )
    assert response.status_code == 422
    body = response.json()
    assert body["success"] is False
    assert body["function"] == function_id
    assert body["request_id"] == "payload-proof"
    assert body["error"] == {
        "code": "envelope_invalid",
        "message": "payload must be a JSON object; send payload: {} for an empty payload",
        "jsonpath": None,
        "recovery_hint": None,
    }


@pytest.mark.parametrize("fields", [{}, {"payload": {}}])
def test_empty_object_or_omitted_payload_dispatches(monkeypatch, fields):
    captured = []

    def dispatch(request, **kwargs):
        captured.append(request.payload)
        return FunctionCallResponse(
            success=True, function=request.function, version="v1"
        )

    monkeypatch.setattr(yoke_function_dispatch, "dispatch", dispatch)
    monkeypatch.setattr(proxy_transport, "relays_to_server", lambda: False)
    body, status = function_proxy.proxy_function_call(
        {"function": "organizations.get", **fields}
    )
    assert status == 200 and body["success"] is True, body
    assert captured == [{}]


def test_payload_binding_failure_is_a_typed_response(ui_client, monkeypatch):
    from yoke_contracts.session_control import sender_surface

    def failed_binding(*args, **kwargs):
        raise ValueError("binding failed")

    monkeypatch.setattr(sender_surface, "with_web_form_sender_surface", failed_binding)
    response = ui_client.post(
        f"/api/functions/call?token={_TOKEN}",
        json={"function": "organizations.get", "payload": {}},
    )
    assert response.status_code == 500
    assert response.json()["error"]["code"] == "handler_exception"
    assert "binding failed" in response.json()["error"]["message"]
