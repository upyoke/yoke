"""Response size and sensitive-value boundaries for Yoke HTTPS dispatch."""

from __future__ import annotations

import io
import json
import urllib.error

import pytest

from runtime.api.cli.test_yoke_transport import _FakeResponse, _request
from yoke_cli.transport import dispatcher as yoke_dispatcher
from yoke_cli.transport import https as yoke_transport
from yoke_cli.transport.https import HttpsConnection, relay_https
from yoke_cli.transport.https_response_policy import FUNCTION_RESPONSE_LIMIT_BYTES
from yoke_contracts.api.function_call import ActorContext, TargetRef


@pytest.mark.parametrize("http_error", [False, True])
def test_relay_rejects_oversize_response_body(
    monkeypatch: pytest.MonkeyPatch, http_error: bool,
) -> None:
    body = b"x" * (FUNCTION_RESPONSE_LIMIT_BYTES + 1)

    def fake_urlopen(req, timeout=None):
        if http_error:
            raise urllib.error.HTTPError(
                req.full_url, 502, "Bad Gateway", {}, io.BytesIO(body),
            )
        return _FakeResponse(body)

    monkeypatch.setattr(yoke_transport, "open_no_redirect", fake_urlopen)
    response = relay_https(
        _request(), HttpsConnection(api_url="https://api.example", token="actor")
    )
    assert response.success is False
    assert response.error.code == "https_transport_failed"
    assert "size limit" in response.error.message


def test_sensitive_dispatch_redacts_hostile_non_envelope_echo(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    secret = "transient-github-user-token"
    monkeypatch.setattr(
        yoke_dispatcher.https_transport,
        "resolve_https_connection",
        lambda: HttpsConnection(api_url="https://api.example", token="actor"),
    )

    def fake_urlopen(req, timeout=None):
        raise urllib.error.HTTPError(
            req.full_url, 502, "Bad Gateway", {},
            io.BytesIO(f"service echoed {secret}".encode("utf-8")),
        )

    monkeypatch.setattr(yoke_transport, "open_no_redirect", fake_urlopen)
    response = yoke_dispatcher.call_dispatcher(
        function_id="projects.github_binding.bind",
        target=TargetRef(kind="global"),
        payload={"github_user_access_token": secret},
        actor=ActorContext(session_id="s1"),
        sensitive_values=(secret,),
    )
    serialized = json.dumps(response.model_dump(mode="json"))
    assert response.success is False
    assert secret not in serialized
    assert "<redacted>" in serialized
