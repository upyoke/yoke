"""TLS verification evidence survives relay and bounded JSON boundaries."""

from __future__ import annotations

import errno
import socket
import ssl
import urllib.error
import urllib.request

import pytest

from runtime.api.cli.https_relay_security_test_support import (
    CAPABILITY_SECRET,
    CONNECTION,
    NESTED_PASSWORD,
    TRANSPORT_TOKEN,
    USER_TOKEN,
    sensitive_request,
)
from yoke_cli.transport import https as relay
from yoke_cli.transport import https_relay_outcome as outcome
from yoke_cli.transport.bounded_json_http import (
    BoundedJsonHttpNetworkError,
    request_json,
)
from yoke_cli.transport.https_retry_policy import (
    CONNECTION_ATTEMPTS,
    is_sandbox_denial,
    should_retry_connection,
)


def certificate_error(code=None, reason="certificate validation failed"):
    error = ssl.SSLCertVerificationError(1, reason)
    if code is not None:
        error.verify_code = code
        error.verify_message = reason
    return error


@pytest.fixture(autouse=True)
def no_telemetry(monkeypatch):
    monkeypatch.setattr(relay, "record_outcome", lambda *_a, **_k: None)


@pytest.mark.parametrize("wrapped", [False, True])
@pytest.mark.parametrize("recovery", [None, "LAUNCHER REPAIR"])
@pytest.mark.parametrize(
    ("code", "reason", "repair"),
    [
        (10, "certificate has expired", "Renew the expired"),
        (62, "Hostname mismatch", "Correct the endpoint hostname"),
        (64, "IP address mismatch", "Correct the endpoint hostname"),
        (20, "unable to get local issuer certificate", "trusted CA store"),
        (18, "self-signed certificate", "trusted CA store"),
        (9, "certificate is not yet valid", "validity start time"),
        (None, "certificate validation failed", "inspect the certificate"),
    ],
)
def test_certificate_failure_stops_and_preserves_reason(
    monkeypatch,
    wrapped,
    recovery,
    code,
    reason,
    repair,
):
    failure = certificate_error(code, reason)
    if wrapped:
        failure = urllib.error.URLError(failure)
    opens, sleeps = [], []

    def open_request(*args, **kwargs):
        opens.append(args)
        raise failure

    monkeypatch.setattr(relay, "_open_function_relay", open_request)
    monkeypatch.setattr(outcome, "sandbox_recovery", lambda: recovery)
    response = relay.relay_https(sensitive_request(), CONNECTION, sleep=sleeps.append)
    assert len(opens) == 1
    assert sleeps == []
    assert response.error.code == "https_transport_failed"
    assert "certificate_validation_failed" in response.error.message
    assert reason in response.error.message
    assert repair in response.error.recovery_hint
    assert "Retrying unchanged will not help" in response.error.recovery_hint
    assert "TLS verification enabled" in response.error.recovery_hint
    assert "sandbox" not in response.error.recovery_hint
    assert "LAUNCHER REPAIR" not in response.error.recovery_hint
    if code is None:
        assert "expired" not in response.error.recovery_hint
    assert should_retry_connection(0, CONNECTION.api_url, failure) is False
    assert is_sandbox_denial(failure) is False


@pytest.mark.parametrize("wrapped", [False, True])
@pytest.mark.parametrize("replay_safe", [False, True])
def test_bounded_json_preserves_certificate_evidence(wrapped, replay_safe):
    secret = "private-bearer-secret"
    failure = certificate_error(10, f"certificate has expired {secret}\n\x1b[31m")
    if wrapped:
        failure = urllib.error.URLError(failure)

    def opener(*args, **kwargs):
        raise failure

    request = urllib.request.Request(
        "https://api.example.test/probe",
        headers={"Authorization": f"Bearer {secret}"},
        method="GET" if replay_safe else "POST",
    )
    with pytest.raises(BoundedJsonHttpNetworkError) as caught:
        request_json(request, timeout_seconds=1, replay_safe=replay_safe, opener=opener)
    message = str(caught.value)
    assert "certificate_validation_failed" in message
    assert "certificate has expired" in message
    assert "Renew the expired" in message
    assert secret not in message
    assert "\n" not in message
    assert "\x1b" not in message


@pytest.mark.parametrize("wrapped", [False, True])
def test_certificate_diagnostic_redacts_all_relay_secrets(monkeypatch, wrapped):
    secrets = (TRANSPORT_TOKEN, USER_TOKEN, NESTED_PASSWORD, CAPABILITY_SECRET)
    failure = certificate_error(
        62, "Hostname mismatch " + " ".join(secrets) + "\n\x1b[31m" + "x" * 2048
    )
    if wrapped:
        failure = urllib.error.URLError(failure)

    def opener(*args, **kwargs):
        raise failure

    monkeypatch.setattr(relay, "_open_function_relay", opener)
    response = relay.relay_https(sensitive_request(), CONNECTION)
    assert all(secret not in response.model_dump_json() for secret in secrets)
    assert len(response.error.message) <= 512
    assert "\n" not in response.error.message
    assert "\x1b" not in response.error.message
    assert "<redacted>" in response.error.message


@pytest.mark.parametrize("recovery", [None, "LAUNCHER REPAIR"])
@pytest.mark.parametrize("wrapped", [False, True])
@pytest.mark.parametrize(
    ("failure", "attempts"),
    [
        (PermissionError(errno.EPERM, "denied"), 1),
        (PermissionError(errno.EACCES, "denied"), 1),
        (ConnectionResetError("reset"), CONNECTION_ATTEMPTS),
        (ssl.SSLError(ssl.SSL_ERROR_SSL, "TLS protocol failure"), CONNECTION_ATTEMPTS),
        (
            socket.gaierror(socket.EAI_NONAME, "unknown DNS failure"),
            CONNECTION_ATTEMPTS,
        ),
    ],
)
def test_permission_and_transient_budgets_with_and_without_harness(
    monkeypatch,
    recovery,
    wrapped,
    failure,
    attempts,
):
    if wrapped:
        failure = urllib.error.URLError(failure)
    opens, sleeps = [], []

    def opener(request, **kwargs):
        opens.append(request.data)
        raise failure

    monkeypatch.setattr(relay, "_open_function_relay", opener)
    monkeypatch.setattr(outcome, "sandbox_recovery", lambda: recovery)
    response = relay.relay_https(sensitive_request(), CONNECTION, sleep=sleeps.append)
    assert len(opens) == attempts
    assert len(sleeps) == attempts - 1
    assert all(body == opens[0] for body in opens)
    if attempts == 1:
        assert "operating system denied permission" in response.error.recovery_hint
    else:
        assert "cause is unknown" in response.error.recovery_hint
        assert "LAUNCHER REPAIR" not in response.error.recovery_hint
        assert "sandbox" not in response.error.recovery_hint


@pytest.mark.parametrize("wrapped", [False, True])
def test_default_bounded_relay_open_preserves_certificate(monkeypatch, wrapped):
    from yoke_cli.transport import bounded_http_open_policy as policy

    failure = certificate_error(10, "certificate has expired")
    if wrapped:
        failure = urllib.error.URLError(failure)
    opens, sleeps = [], []

    def opener(*args, **kwargs):
        opens.append(1)
        raise failure

    monkeypatch.setattr(policy, "open_https_caller_owned", opener)
    response = relay.relay_https(sensitive_request(), CONNECTION, sleep=sleeps.append)
    assert opens == [1] and sleeps == []
    assert "certificate has expired" in response.error.message


def test_http_error_read_does_not_retry_a_certificate_failure(monkeypatch):
    failure = certificate_error(20, "unable to get local issuer certificate")

    def read(*args, **kwargs):
        raise failure

    monkeypatch.setattr(outcome, "read_bounded_response", read)
    opens, sleeps = [], []

    def opener(*args, **kwargs):
        opens.append(1)
        raise urllib.error.HTTPError(CONNECTION.api_url, 503, "unavailable", {}, None)

    monkeypatch.setattr(relay, "_open_function_relay", opener)
    response = relay.relay_https(sensitive_request(), CONNECTION, sleep=sleeps.append)
    assert opens == [1] and sleeps == []
    assert "unable to get local issuer certificate" in response.error.message
