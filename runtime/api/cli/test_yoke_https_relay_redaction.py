"""Hostile secret-echo tests for the generic HTTPS function relay."""

from __future__ import annotations

import io
import json
import urllib.error

from runtime.api.cli.https_relay_security_test_support import (
    CAPABILITY_SECRET,
    CONNECTION,
    FakeResponse,
    NESTED_PASSWORD,
    TRANSPORT_TOKEN,
    USER_TOKEN,
    envelope,
    sensitive_request,
    serialized_response,
)
from yoke_cli.transport import https as relay_module
from yoke_cli.transport.dispatcher import emit_response
from yoke_cli.transport.https import relay_https
from yoke_cli.transport.https_response_policy import (
    REDACTED,
    collect_request_secrets,
)


def _all_secrets() -> tuple[str, ...]:
    return (
        USER_TOKEN,
        NESTED_PASSWORD,
        CAPABILITY_SECRET,
        TRANSPORT_TOKEN,
    )


def _assert_scrubbed(value: str) -> None:
    for secret in _all_secrets():
        assert secret not in value


def test_nested_sensitive_keys_and_named_value_are_classified() -> None:
    secrets = collect_request_secrets(
        sensitive_request(), transport_token=TRANSPORT_TOKEN
    )

    assert set(_all_secrets()) <= set(secrets)


def test_typed_success_scrubs_results_keys_warnings_and_client_output(
    monkeypatch, capsys
) -> None:
    body = envelope(
        result={
            f"echo-key-{USER_TOKEN}": (
                f"first={USER_TOKEN}; second={USER_TOKEN}; "
                f"password={NESTED_PASSWORD}; secret={CAPABILITY_SECRET}; "
                f"bearer={TRANSPORT_TOKEN}"
            )
        },
        warnings=[
            {
                "code": "hostile_echo",
                "step": "relay",
                "detail": f"warning repeated {USER_TOKEN} {USER_TOKEN}",
            }
        ],
    )
    monkeypatch.setattr(
        relay_module,
        "open_no_redirect",
        lambda request, timeout=None: FakeResponse(body),
    )

    response = relay_https(sensitive_request(), CONNECTION)

    assert response.success is True
    serialized = serialized_response(response)
    _assert_scrubbed(serialized)
    assert serialized.count(REDACTED) >= 7

    assert emit_response(response, json_mode=True) == 0
    _assert_scrubbed(capsys.readouterr().out)


def test_typed_http_error_scrubs_error_fields(monkeypatch) -> None:
    body = envelope(
        success=False,
        error={
            "code": "remote_denied",
            "message": f"denied {USER_TOKEN} then {USER_TOKEN}",
            "jsonpath": f"$.payload.{NESTED_PASSWORD}",
            "recovery_hint": (f"retry {CAPABILITY_SECRET} with {TRANSPORT_TOKEN}"),
        },
    )

    def reject(request, timeout=None):
        raise urllib.error.HTTPError(
            request.full_url,
            403,
            "Forbidden",
            {},
            io.BytesIO(body),
        )

    monkeypatch.setattr(relay_module, "open_no_redirect", reject)

    response = relay_https(sensitive_request(), CONNECTION)

    assert response.success is False
    assert response.error is not None
    assert response.error.code == "remote_denied"
    _assert_scrubbed(serialized_response(response))


def test_short_boundary_error_scrubs_message_and_recovery(monkeypatch) -> None:
    body = json.dumps(
        {
            "success": False,
            "error": {
                "code": "authentication_unknown",
                "message": f"unknown {USER_TOKEN} {USER_TOKEN}",
                "recovery_hint": f"replace {TRANSPORT_TOKEN}",
            },
        }
    ).encode("utf-8")

    def reject(request, timeout=None):
        raise urllib.error.HTTPError(
            request.full_url,
            401,
            "Unauthorized",
            {},
            io.BytesIO(body),
        )

    monkeypatch.setattr(relay_module, "open_no_redirect", reject)

    response = relay_https(sensitive_request(), CONNECTION)

    assert response.error is not None
    assert response.error.code == "authentication_unknown"
    _assert_scrubbed(serialized_response(response))


def test_non_envelope_excerpt_scrubs_repeated_echo(monkeypatch) -> None:
    body = (
        f"gateway echoed {USER_TOKEN}/{USER_TOKEN} and bearer {TRANSPORT_TOKEN}"
    ).encode("utf-8")

    def reject(request, timeout=None):
        raise urllib.error.HTTPError(
            request.full_url,
            502,
            "Bad Gateway",
            {},
            io.BytesIO(body),
        )

    monkeypatch.setattr(relay_module, "open_no_redirect", reject)

    response = relay_https(sensitive_request(), CONNECTION)

    assert response.error is not None
    assert "non-envelope body" in response.error.message
    assert REDACTED in response.error.message
    _assert_scrubbed(serialized_response(response))


def test_engine_skew_header_echo_is_scrubbed_from_stderr(monkeypatch, capsys) -> None:
    monkeypatch.setattr(relay_module, "_skew_warned", False)
    monkeypatch.setattr(
        relay_module, "local_handshake_version", lambda: "local-version"
    )
    headers = {
        relay_module.ENGINE_VERSION_HEADER: (
            f"remote-{USER_TOKEN}-{USER_TOKEN}-{TRANSPORT_TOKEN}"
        )
    }
    monkeypatch.setattr(
        relay_module,
        "open_no_redirect",
        lambda request, timeout=None: FakeResponse(envelope(), headers),
    )

    response = relay_https(sensitive_request(), CONNECTION)

    assert response.success is True
    stderr = capsys.readouterr().err
    assert "server engine version" in stderr
    assert REDACTED in stderr
    _assert_scrubbed(stderr)
