"""Hostile response-bound tests for the generic HTTPS function relay."""

from __future__ import annotations

import http.client
import io
import json
import urllib.error
import urllib.request

import pytest

from runtime.api.cli.https_relay_security_test_support import (
    CONNECTION,
    FakeResponse,
    NoReadResponse,
    USER_TOKEN,
    envelope,
    sensitive_request,
    serialized_response,
)
from yoke_cli.transport import https as relay_module
from yoke_cli.transport.https import relay_https
from yoke_cli.transport.https_response_policy import (
    FUNCTION_RESPONSE_LIMIT_BYTES,
)
from yoke_cli.transport.https_urlopen import NoRedirect


def _assert_transport_failure(response, message_fragment: str) -> None:
    assert response.success is False
    assert response.error is not None
    assert response.error.code == "https_transport_failed"
    assert message_fragment in response.error.message
    assert USER_TOKEN not in serialized_response(response)


@pytest.mark.parametrize("status", [301, 302, 303, 307, 308])
def test_credential_bearing_relay_refuses_redirects(status: int) -> None:
    request = urllib.request.Request(
        CONNECTION.functions_url,
        data=b"sensitive-body",
        method="POST",
        headers={"Authorization": f"Bearer {CONNECTION.token}"},
    )

    redirected = NoRedirect().redirect_request(
        request,
        io.BytesIO(),
        status,
        "Redirect",
        {"Location": "https://hostile.example/capture"},
        "https://hostile.example/capture",
    )

    assert redirected is None


def test_success_content_length_rejects_before_read(monkeypatch) -> None:
    response_stream = NoReadResponse(
        b"",
        {"Content-Length": str(FUNCTION_RESPONSE_LIMIT_BYTES + 1)},
    )
    monkeypatch.setattr(
        relay_module,
        "open_no_redirect",
        lambda request, timeout=None: response_stream,
    )

    response = relay_https(sensitive_request(), CONNECTION)

    _assert_transport_failure(response, "exceeded the size limit")
    assert response_stream.read_sizes == []


def test_success_stream_read_uses_one_byte_overflow_sentinel(
    monkeypatch,
) -> None:
    response_stream = FakeResponse(b"x" * (FUNCTION_RESPONSE_LIMIT_BYTES + 1))
    monkeypatch.setattr(
        relay_module,
        "open_no_redirect",
        lambda request, timeout=None: response_stream,
    )

    response = relay_https(sensitive_request(), CONNECTION)

    _assert_transport_failure(response, "exceeded the size limit")
    assert response_stream.read_sizes == [FUNCTION_RESPONSE_LIMIT_BYTES + 1]


def test_http_error_content_length_rejects_before_read(monkeypatch) -> None:
    error_stream = NoReadResponse(b"")

    def reject(request, timeout=None):
        raise urllib.error.HTTPError(
            request.full_url,
            502,
            "Bad Gateway",
            {"Content-Length": str(FUNCTION_RESPONSE_LIMIT_BYTES + 1)},
            error_stream,
        )

    monkeypatch.setattr(relay_module, "open_no_redirect", reject)

    response = relay_https(sensitive_request(), CONNECTION)

    _assert_transport_failure(response, "exceeded the size limit")
    assert error_stream.read_sizes == []


def test_http_error_stream_is_bounded_without_content_length(
    monkeypatch,
) -> None:
    error_stream = FakeResponse(
        USER_TOKEN.encode("utf-8") + b"x" * FUNCTION_RESPONSE_LIMIT_BYTES
    )

    def reject(request, timeout=None):
        raise urllib.error.HTTPError(
            request.full_url,
            502,
            "Bad Gateway",
            {},
            error_stream,
        )

    monkeypatch.setattr(relay_module, "open_no_redirect", reject)

    response = relay_https(sensitive_request(), CONNECTION)

    _assert_transport_failure(response, "exceeded the size limit")
    assert error_stream.read_sizes == [FUNCTION_RESPONSE_LIMIT_BYTES + 1]


def test_exact_declared_length_keeps_ordinary_envelope_behavior(
    monkeypatch,
) -> None:
    body = envelope(result={"rows": [1]})
    response_stream = FakeResponse(body, {"Content-Length": str(len(body))})
    monkeypatch.setattr(
        relay_module,
        "open_no_redirect",
        lambda request, timeout=None: response_stream,
    )

    response = relay_https(sensitive_request(), CONNECTION)

    assert response.success is True
    assert response.result == {"rows": [1]}
    assert response_stream.read_sizes == [FUNCTION_RESPONSE_LIMIT_BYTES + 1]


def test_invalid_utf8_becomes_detail_free_typed_failure(monkeypatch) -> None:
    monkeypatch.setattr(
        relay_module,
        "open_no_redirect",
        lambda request, timeout=None: FakeResponse(b"\xff\xfe"),
    )

    response = relay_https(sensitive_request(), CONNECTION)

    _assert_transport_failure(response, "not valid UTF-8")
    assert "\\xff" not in serialized_response(response)


def test_malformed_json_does_not_echo_body_or_parser_detail(
    monkeypatch,
) -> None:
    body = f'{{"echo":"{USER_TOKEN}"'.encode("utf-8")
    monkeypatch.setattr(
        relay_module,
        "open_no_redirect",
        lambda request, timeout=None: FakeResponse(body),
    )

    response = relay_https(sensitive_request(), CONNECTION)

    _assert_transport_failure(response, "not valid JSON")
    assert "line 1 column" not in serialized_response(response)


def test_deeply_nested_json_becomes_typed_malformed_failure(
    monkeypatch,
) -> None:
    body = b"[" * 2_000 + b"0" + b"]" * 2_000
    monkeypatch.setattr(
        relay_module,
        "open_no_redirect",
        lambda request, timeout=None: FakeResponse(body),
    )

    response = relay_https(sensitive_request(), CONNECTION)

    _assert_transport_failure(response, "exceeded the nesting limit")


def test_malformed_short_boundary_error_cannot_escape_validation(
    monkeypatch,
) -> None:
    body = json.dumps(
        {
            "success": False,
            "error": {
                "code": "denied",
                "message": "hostile boundary",
                "recovery_hint": {"echo": USER_TOKEN},
            },
        }
    ).encode("utf-8")

    def reject(request, timeout=None):
        raise urllib.error.HTTPError(
            request.full_url,
            401,
            "Unauthorized",
            {},
            FakeResponse(body),
        )

    monkeypatch.setattr(relay_module, "open_no_redirect", reject)

    response = relay_https(sensitive_request(), CONNECTION)

    _assert_transport_failure(response, "non-envelope body")
    assert "recovery_hint" not in response.error.message


def test_incomplete_read_partial_body_is_never_exposed(monkeypatch) -> None:
    class IncompleteResponse(FakeResponse):
        def read(self, size: int = -1) -> bytes:
            self.read_sizes.append(size)
            raise http.client.IncompleteRead(USER_TOKEN.encode("utf-8"), 999)

    monkeypatch.setattr(
        relay_module,
        "open_no_redirect",
        lambda request, timeout=None: IncompleteResponse(b""),
    )

    response = relay_https(sensitive_request(), CONNECTION)

    _assert_transport_failure(response, "could not reach")
    assert "IncompleteRead" not in serialized_response(response)


@pytest.mark.parametrize(
    "failure",
    [
        TimeoutError(f"timeout echoed {USER_TOKEN}"),
        OSError(f"socket echoed {USER_TOKEN}"),
        urllib.error.URLError(f"url echoed {USER_TOKEN}"),
    ],
)
def test_direct_network_failures_are_generic_and_scrubbed(monkeypatch, failure) -> None:
    def fail(request, timeout=None):
        raise failure

    monkeypatch.setattr(relay_module, "open_no_redirect", fail)

    response = relay_https(sensitive_request(), CONNECTION)

    _assert_transport_failure(response, "could not reach")
    assert "echoed" not in serialized_response(response)
