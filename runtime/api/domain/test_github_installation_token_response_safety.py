"""Adversarial response tests for installation-token minting."""

from __future__ import annotations

import json
import unicodedata
import urllib.error

import pytest

from yoke_core.domain import github_app_installation_token_transport as transport
from yoke_core.domain import github_app_installation_tokens as tokens
from yoke_core.domain.github_app_token_models import (
    GitHubAppTokenError,
    GitHubAppTokenResponseDecodeError,
    GitHubAppTokenResponseError,
    GitHubAppTokenResponseSizeError,
)


APP_JWT = "app.jwt.request.secret"


class _RecordingReader:
    def __init__(self, payload: bytes, *, headers: dict[str, str] | None = None):
        self.payload = payload
        self.headers = headers or {}
        self.status = 201
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


@pytest.fixture(autouse=True)
def _fixed_app_jwt(monkeypatch) -> None:
    monkeypatch.setattr(tokens, "generate_app_jwt", lambda **_kwargs: APP_JWT)


def _mint(opener):
    return tokens.mint_installation_token(
        issuer=123,
        private_key_pem=b"not-used-by-test",
        installation_id=456,
        opener=opener,
    )


def test_token_json_accepts_exact_boundary_and_uses_sentinel(monkeypatch) -> None:
    raw = json.dumps(
        {
            "token": "ghs_installation",
            "expires_at": "2099-01-01T00:00:00Z",
        }
    ).encode("utf-8")
    monkeypatch.setattr(transport, "GITHUB_SMALL_RESPONSE_LIMIT_BYTES", len(raw))
    response = _RecordingReader(raw)

    minted = _mint(lambda *_args, **_kwargs: response)

    assert minted.token == "ghs_installation"
    assert response.read_sizes == [len(raw) + 1]


def test_token_json_oversize_is_typed_and_detail_free(monkeypatch) -> None:
    monkeypatch.setattr(transport, "GITHUB_SMALL_RESPONSE_LIMIT_BYTES", 8)
    response = _RecordingReader(b"123456789")

    with pytest.raises(GitHubAppTokenResponseSizeError) as exc_info:
        _mint(lambda *_args, **_kwargs: response)

    assert APP_JWT not in str(exc_info.value)
    assert response.read_sizes == [9]
    assert exc_info.value.__cause__ is None


def test_token_json_invalid_utf8_is_typed(monkeypatch) -> None:
    response = _RecordingReader(b"\xff")

    with pytest.raises(GitHubAppTokenResponseDecodeError) as exc_info:
        _mint(lambda *_args, **_kwargs: response)

    assert APP_JWT not in str(exc_info.value)
    assert exc_info.value.__cause__ is None


def test_success_response_cannot_echo_app_jwt(monkeypatch) -> None:
    raw = json.dumps({"token": APP_JWT, "expires_at": "2099-01-01T00:00:00Z"}).encode(
        "utf-8"
    )
    response = _RecordingReader(raw)

    with pytest.raises(GitHubAppTokenResponseDecodeError) as exc_info:
        _mint(lambda *_args, **_kwargs: response)

    assert APP_JWT not in str(exc_info.value)


def test_http_error_body_is_bounded_and_scrubs_app_jwt(monkeypatch) -> None:
    monkeypatch.setattr(transport, "GITHUB_SMALL_RESPONSE_LIMIT_BYTES", 256)
    body = _RecordingReader(
        f"prefix{APP_JWT}suffix repeated={APP_JWT}:{APP_JWT}".encode("utf-8")
    )
    error = urllib.error.HTTPError("https://api.github.com/x", 401, APP_JWT, {}, body)

    def fail(*_args, **_kwargs):
        raise error

    with pytest.raises(GitHubAppTokenResponseError) as exc_info:
        _mint(fail)

    rendered = f"{exc_info.value} {exc_info.value.body}"
    assert APP_JWT not in rendered
    assert body.read_sizes == [257]
    assert exc_info.value.status == 401
    assert exc_info.value.__cause__ is None


def test_http_error_body_is_capped_and_terminal_safe() -> None:
    hostile = f"denied\x1b]8;;https://evil.example\x07{APP_JWT}\u202e" + "x" * 6000
    body = _RecordingReader(hostile.encode("utf-8"))
    error = urllib.error.HTTPError("https://api.github.com/x", 401, APP_JWT, {}, body)

    def fail(*_args, **_kwargs):
        raise error

    with pytest.raises(GitHubAppTokenResponseError) as exc_info:
        _mint(fail)

    rendered = f"{exc_info.value} {exc_info.value.body}"
    assert APP_JWT not in rendered
    assert len(exc_info.value.body or "") == 4096
    assert not any(
        unicodedata.category(character) in {"Cc", "Cf", "Cs"} for character in rendered
    )


def test_raw_network_reason_is_never_surfaced() -> None:
    def fail(*_args, **_kwargs):
        raise urllib.error.URLError(f"upstream echoed {APP_JWT}")

    with pytest.raises(GitHubAppTokenError) as exc_info:
        _mint(fail)

    assert APP_JWT not in str(exc_info.value)
    assert exc_info.value.__cause__ is None


@pytest.mark.parametrize("failure_type", [TimeoutError, OSError])
def test_direct_network_failures_are_normalized(failure_type) -> None:
    def fail(*_args, **_kwargs):
        raise failure_type(APP_JWT)

    with pytest.raises(GitHubAppTokenError) as exc_info:
        _mint(fail)

    assert APP_JWT not in str(exc_info.value)
    assert exc_info.value.__cause__ is None


def test_hostile_reader_exception_is_detail_free() -> None:
    class _BrokenReader(_RecordingReader):
        def read(self, size: int = -1) -> bytes:
            del size
            raise RuntimeError(APP_JWT)

    with pytest.raises(GitHubAppTokenError) as exc_info:
        _mint(lambda *_args, **_kwargs: _BrokenReader(b""))

    assert APP_JWT not in str(exc_info.value)
    assert exc_info.value.__cause__ is None
