"""Hostile secret-echo tests for the generic HTTPS function relay."""

from __future__ import annotations

import io
import json
import urllib.error

import pytest

from runtime.api.cli.https_relay_security_test_support import (
    CONNECTION,
    FakeResponse,
    TRANSPORT_TOKEN,
    USER_TOKEN,
    declared_secret_request,
    envelope,
    sensitive_request,
    serialized_response,
)
from yoke_cli.transport import https as relay_module
from yoke_cli.transport import https_engine_handshake as handshake_module
from yoke_cli.transport.dispatcher import emit_response
from yoke_cli.transport.https import relay_https
from yoke_cli.transport.https_response_policy import (
    REDACTED,
    collect_request_secrets,
)
from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)


_NON_OBVIOUS_ACTIONS_SECRET = "postgres://relay-user:relay-password@db.example/app"
_PUBLIC_CREDENTIALS_ACTION = "aws-actions/configure-aws-credentials@immutable-sha"


def _pack_bundle_request() -> FunctionCallRequest:
    return FunctionCallRequest(
        function="packs.bundle.get",
        actor=ActorContext(session_id="pack-bundle-relay-test"),
        target=TargetRef(kind="global"),
        request_id="pack-bundle-relay-request",
        payload={
            "project": "example",
            "pack": "production-deploy",
            "version": "1.0.0",
            "render_values": {
                "configure_aws_credentials_action": _PUBLIC_CREDENTIALS_ACTION,
            },
        },
    )


def _assert_scrubbed(value: str) -> None:
    for secret in (USER_TOKEN, TRANSPORT_TOKEN):
        assert secret not in value


@pytest.mark.parametrize(
    ("function", "payload", "expected"),
    [
        ("github_actions.secret.set", {"value": USER_TOKEN}, {USER_TOKEN}),
        (
            "projects.capability_secret.set",
            {"key": "DATABASE_URL", "value": USER_TOKEN},
            {USER_TOKEN},
        ),
        (
            "projects.pulumi_state.checkpoint_import",
            {"secrets_provider": USER_TOKEN, "encrypted_key": "encrypted-material"},
            {USER_TOKEN, "encrypted-material"},
        ),
        ("projects.capability_secret.set", {"value": None}, set()),
        ("projects.capability_secret.set", {"value": ""}, set()),
        ("projects.capability_secret.set", {}, set()),
    ],
)
def test_declared_payload_fields(function, payload, expected) -> None:
    request = sensitive_request().model_copy(
        update={"function": function, "payload": payload}
    )
    assert set(collect_request_secrets(request, transport_token=TRANSPORT_TOKEN)) == (
        expected | {TRANSPORT_TOKEN}
    )


def test_pack_render_values_remain_public_for_checksum_protected_source() -> None:
    secrets = collect_request_secrets(
        _pack_bundle_request(), transport_token=TRANSPORT_TOKEN
    )

    assert _PUBLIC_CREDENTIALS_ACTION not in secrets
    assert TRANSPORT_TOKEN in secrets


@pytest.mark.parametrize(
    ("function", "field"),
    [
        ("github_actions.secret.set", "value"),
        ("projects.capability_secret.set", "value"),
        ("projects.pulumi_state.checkpoint_import", "secrets_provider"),
        ("projects.pulumi_state.checkpoint_import", "encrypted_key"),
    ],
)
def test_typed_declared_secret_echo_is_scrubbed(
    monkeypatch,
    function,
    field,
) -> None:
    body = envelope(
        function=function,
        result={"hostile_echo": _NON_OBVIOUS_ACTIONS_SECRET},
    )
    monkeypatch.setattr(
        relay_module,
        "open_no_redirect",
        lambda request, timeout=None: FakeResponse(body),
    )

    response = relay_https(
        declared_secret_request(function, field, _NON_OBVIOUS_ACTIONS_SECRET),
        CONNECTION,
    )

    assert response.success is True
    assert _NON_OBVIOUS_ACTIONS_SECRET not in serialized_response(response)
    assert REDACTED in serialized_response(response)


@pytest.mark.parametrize(
    ("function", "field"),
    [
        ("github_actions.secret.set", "value"),
        ("projects.capability_secret.set", "value"),
        ("projects.pulumi_state.checkpoint_import", "secrets_provider"),
        ("projects.pulumi_state.checkpoint_import", "encrypted_key"),
    ],
)
def test_non_envelope_declared_secret_echo_is_scrubbed(
    monkeypatch,
    function,
    field,
) -> None:
    body = f"gateway echoed {_NON_OBVIOUS_ACTIONS_SECRET}".encode("utf-8")

    def reject(request, timeout=None):
        raise urllib.error.HTTPError(
            request.full_url,
            502,
            "Bad Gateway",
            {},
            io.BytesIO(body),
        )

    monkeypatch.setattr(relay_module, "open_no_redirect", reject)

    response = relay_https(
        declared_secret_request(function, field, _NON_OBVIOUS_ACTIONS_SECRET),
        CONNECTION,
    )

    assert response.error is not None
    assert _NON_OBVIOUS_ACTIONS_SECRET not in serialized_response(response)
    assert REDACTED in response.error.message


def test_typed_success_scrubs_results_keys_warnings_and_client_output(
    monkeypatch, capsys
) -> None:
    body = envelope(
        result={
            f"echo-key-{USER_TOKEN}": (
                f"first={USER_TOKEN}; second={USER_TOKEN}; "
                f"password={USER_TOKEN}; secret={USER_TOKEN}; "
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
            "jsonpath": f"$.payload.{USER_TOKEN}",
            "recovery_hint": (f"retry {USER_TOKEN} with {TRANSPORT_TOKEN}"),
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
    assert REDACTED in response.error.message
    _assert_scrubbed(serialized_response(response))


def test_engine_version_header_never_reaches_stderr(monkeypatch, capsys) -> None:
    """A sensitive header echo cannot leak from a banner that no longer prints.

    The handshake used to echo the advertised version into a stderr advisory,
    which had to be scrubbed. It prints nothing now, so the header has no path
    to the terminal at all.
    """
    monkeypatch.setattr(
        handshake_module, "local_handshake_version", lambda: "local-version"
    )
    headers = {
        handshake_module.ENGINE_VERSION_HEADER: (
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
    captured = capsys.readouterr()
    assert captured.err == ""
    assert USER_TOKEN not in captured.out
    assert TRANSPORT_TOKEN not in captured.out


def test_public_nested_values_are_untouched():
    request = FunctionCallRequest(
        function="test_machine.operation.submit",
        actor=ActorContext(session_id="proof-client"),
        target=TargetRef(kind="global"),
        request_id="proof-request",
        payload={
            "artifacts": [{"token": "desktop", "password": USER_TOKEN}],
            "checks": [{"artifact_token": "desktop", "token": USER_TOKEN}],
        },
    )
    secrets = collect_request_secrets(request, transport_token=TRANSPORT_TOKEN)
    assert "desktop" not in secrets
    assert secrets == (TRANSPORT_TOKEN,)
    from yoke_cli.transport.https_response_policy import parse_typed_response

    response = parse_typed_response(
        envelope(
            function=request.function,
            result={
                "desktop_session": "started",
                "artifact_key": "proof/desktop.png",
                "hostile_echo": USER_TOKEN,
            },
        ),
        sensitive_values=secrets,
    )
    assert response.result["desktop_session"] == "started"
    assert response.result["artifact_key"] == "proof/desktop.png"
    assert response.result["hostile_echo"] == USER_TOKEN
