"""Adversarial response tests for the shared GitHub REST transport."""

from __future__ import annotations

import urllib.error

import pytest

from yoke_core.domain import gh_rest_transport as transport
from yoke_core.domain.github_app_verification_response import (
    GitHubAppVerificationResponseError,
    read_bounded_verification_response,
)
from yoke_core.domain.github_response_safety import (
    deadline_after,
    redact_exact_secrets,
)


class _RecordingReader:
    def __init__(self, payload: bytes, *, headers: dict[str, str] | None = None):
        self.payload = payload
        self.headers = headers or {}
        self.status = 200
        self.read_sizes: list[int] = []

    def read(self, size: int = -1) -> bytes:
        self.read_sizes.append(size)
        return self.payload if size < 0 else self.payload[:size]

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def close(self) -> None:
        return None


def _request() -> transport.RestRequest:
    return transport.RestRequest(method="GET", path="/repos/o/r")


def test_redaction_scrubs_exact_embedded_and_repeated_secret_occurrences() -> None:
    secret = "ghs_exact_secret"
    text = f"exact={secret} prefix{secret}suffix repeated={secret}:{secret}"

    assert redact_exact_secrets(text, (secret, secret)) == (
        "exact=[REDACTED] prefix[REDACTED]suffix repeated=[REDACTED]:[REDACTED]"
    )


def test_success_read_uses_overflow_sentinel_and_accepts_exact_boundary(
    monkeypatch,
) -> None:
    monkeypatch.setattr(transport, "GITHUB_COLLECTION_RESPONSE_LIMIT_BYTES", 8)
    response = _RecordingReader(b"12345678")
    monkeypatch.setattr(transport, "urlopen", lambda *_args, **_kwargs: response)

    result = transport.request_with_retry(_request(), token="ghs_secret")

    assert result.body == 12_345_678
    assert response.read_sizes == [9]


def test_success_read_rejects_overflow_with_typed_error(monkeypatch) -> None:
    monkeypatch.setattr(transport, "GITHUB_COLLECTION_RESPONSE_LIMIT_BYTES", 8)
    response = _RecordingReader(b"123456789")
    monkeypatch.setattr(transport, "urlopen", lambda *_args, **_kwargs: response)

    with pytest.raises(transport.RestResponseTooLargeError) as exc_info:
        transport.request_with_retry(_request(), token="ghs_secret", max_attempts=1)

    assert exc_info.value.status == 200
    assert response.read_sizes == [9]


def test_declared_oversize_fails_before_body_read(monkeypatch) -> None:
    monkeypatch.setattr(transport, "GITHUB_COLLECTION_RESPONSE_LIMIT_BYTES", 8)
    response = _RecordingReader(b"ignored", headers={"Content-Length": "9"})
    monkeypatch.setattr(transport, "urlopen", lambda *_args, **_kwargs: response)

    with pytest.raises(transport.RestResponseTooLargeError):
        transport.request_with_retry(_request(), token="ghs_secret", max_attempts=1)

    assert response.read_sizes == []


def test_error_read_is_bounded_and_scrubs_exact_bearer(monkeypatch) -> None:
    secret = "ghs_exact_secret"
    body = _RecordingReader(
        f"prefix{secret}suffix repeated={secret}:{secret}".encode("utf-8")
    )
    error = urllib.error.HTTPError("https://api.github.com/x", 401, secret, {}, body)
    monkeypatch.setattr(transport, "GITHUB_SMALL_RESPONSE_LIMIT_BYTES", 256)
    monkeypatch.setattr(
        transport, "urlopen", lambda *_args, **_kwargs: (_ for _ in ()).throw(error)
    )

    with pytest.raises(transport.RestAuthError) as exc_info:
        transport.request_with_retry(_request(), token=secret, max_attempts=1)

    rendered = f"{exc_info.value} {exc_info.value.body}"
    assert secret not in rendered
    assert body.read_sizes == [257]
    assert exc_info.value.__cause__ is None


def test_oversized_error_body_preserves_http_classification(monkeypatch) -> None:
    monkeypatch.setattr(transport, "GITHUB_SMALL_RESPONSE_LIMIT_BYTES", 8)
    body = _RecordingReader(b"123456789")
    error = urllib.error.HTTPError(
        "https://api.github.com/x", 401, "synthetic", {}, body
    )

    def fail(*_args, **_kwargs):
        raise error

    monkeypatch.setattr(transport, "urlopen", fail)

    with pytest.raises(transport.RestAuthError) as exc_info:
        transport.request_with_retry(
            _request(), token="ghs_exact_secret", max_attempts=1
        )

    assert exc_info.value.status == 401
    assert body.read_sizes == [9]


def test_retry_stderr_scrubs_embedded_error_body_secret(monkeypatch, capsys) -> None:
    secret = "ghs_retry_secret"
    body = _RecordingReader(f"prefix{secret}suffix".encode("utf-8"))
    error = urllib.error.HTTPError("https://api.github.com/x", 503, secret, {}, body)
    responses = iter((error, _RecordingReader(b"{}")))

    def open_next(*_args, **_kwargs):
        selected = next(responses)
        if isinstance(selected, Exception):
            raise selected
        return selected

    monkeypatch.setattr(transport, "urlopen", open_next)
    monkeypatch.setattr(transport, "sleep", lambda _seconds: None)

    transport.request_with_retry(_request(), token=secret)

    assert secret not in capsys.readouterr().err


def test_invalid_utf8_raises_typed_detail_free_error(monkeypatch) -> None:
    response = _RecordingReader(b"\xffhostile")
    monkeypatch.setattr(transport, "urlopen", lambda *_args, **_kwargs: response)

    with pytest.raises(transport.RestResponseDecodeError) as exc_info:
        transport.request_with_retry(_request(), token="ghs_secret")

    assert "hostile" not in str(exc_info.value)
    assert exc_info.value.__cause__ is None


def test_invalid_utf8_error_body_preserves_http_classification(monkeypatch) -> None:
    body = _RecordingReader(b"\xffhostile")
    error = urllib.error.HTTPError("https://api.github.com/x", 401, "hostile", {}, body)

    def fail(*_args, **_kwargs):
        raise error

    monkeypatch.setattr(transport, "urlopen", fail)

    with pytest.raises(transport.RestAuthError) as exc_info:
        transport.request_with_retry(_request(), token="ghs_secret", max_attempts=1)

    assert exc_info.value.status == 401
    assert exc_info.value.body == ("GitHub REST error response was not valid UTF-8")
    assert "hostile" not in str(exc_info.value)


def test_raw_network_reason_never_reaches_exception_or_retry_stderr(
    monkeypatch,
    capsys,
) -> None:
    secret = "ghs_network_secret"
    monkeypatch.setattr(transport, "sleep", lambda _seconds: None)

    def unavailable(*_args, **_kwargs):
        raise urllib.error.URLError(f"upstream echoed {secret}")

    monkeypatch.setattr(transport, "urlopen", unavailable)

    with pytest.raises(transport.RestNetworkError) as exc_info:
        transport.request_with_retry(_request(), token=secret, max_attempts=2)

    assert secret not in str(exc_info.value)
    assert secret not in capsys.readouterr().err
    assert exc_info.value.__cause__ is None


@pytest.mark.parametrize("failure_type", [TimeoutError, OSError])
def test_direct_network_failures_are_normalized(monkeypatch, failure_type) -> None:
    secret = "ghs_direct_network_secret"

    def unavailable(*_args, **_kwargs):
        raise failure_type(secret)

    monkeypatch.setattr(transport, "urlopen", unavailable)

    with pytest.raises(transport.RestNetworkError) as exc_info:
        transport.request_with_retry(_request(), token=secret, max_attempts=1)

    assert secret not in str(exc_info.value)
    assert exc_info.value.__cause__ is None


def test_hostile_reader_exception_is_detail_free(monkeypatch) -> None:
    secret = "ghs_reader_secret"

    class _BrokenReader(_RecordingReader):
        def read(self, size: int = -1) -> bytes:
            del size
            raise RuntimeError(secret)

    monkeypatch.setattr(
        transport,
        "urlopen",
        lambda *_args, **_kwargs: _BrokenReader(b""),
    )

    with pytest.raises(transport.RestNetworkError) as exc_info:
        transport.request_with_retry(_request(), token=secret, max_attempts=1)

    assert secret not in str(exc_info.value)
    assert exc_info.value.__cause__ is None


def test_verification_reader_exception_is_detail_free() -> None:
    secret = "ghs_verification_reader_secret"

    class _BrokenVerificationReader:
        def read(self, _size: int = -1) -> bytes:
            raise RuntimeError(secret)

    with pytest.raises(GitHubAppVerificationResponseError) as exc_info:
        read_bounded_verification_response(
            _BrokenVerificationReader(),
            deadline=deadline_after(1.0),
        )

    assert secret not in str(exc_info.value)
    assert exc_info.value.__cause__ is None
