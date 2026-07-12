"""Untrusted GitHub REST diagnostics stay bounded and terminal-safe."""

from __future__ import annotations

import io
import json
import unicodedata
import urllib.error

import pytest

from yoke_core.domain import gh_rest_transport as transport
from yoke_core.domain.github_response_safety import (
    GITHUB_ERROR_BODY_LIMIT_CHARS,
)


TOKEN = "ghs_exact_secret"


def _http_error(status: int, body: bytes) -> urllib.error.HTTPError:
    return urllib.error.HTTPError(
        "https://api.github.com/user",
        status,
        "rejected",
        {"Content-Type": "application/json"},
        io.BytesIO(body),
    )


def _assert_terminal_safe(value: str) -> None:
    assert TOKEN not in value
    assert not any(
        unicodedata.category(character) in {"Cc", "Cf", "Cs"} for character in value
    )


@pytest.fixture(autouse=True)
def _isolate_transport(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(transport._FAKE_DIR_ENV, raising=False)
    monkeypatch.delenv(transport.GITHUB_APP_API_URL_ENV, raising=False)
    monkeypatch.setattr(transport, "sleep", lambda _seconds: None)


def test_http_error_body_is_redacted_neutralized_and_capped(monkeypatch) -> None:
    hostile = f"denied\x1b]8;;https://evil.example\x07{TOKEN}\u202e" + "x" * 6000

    def reject(*_args, **_kwargs):
        raise _http_error(422, hostile.encode("utf-8"))

    monkeypatch.setattr(transport, "urlopen", reject)
    with pytest.raises(transport.RestUnprocessableError) as exc_info:
        transport.request_with_retry(
            transport.RestRequest(method="POST", path="/repos/o/r/pulls"),
            token=TOKEN,
            max_attempts=1,
        )

    body = exc_info.value.body or ""
    assert len(body) == GITHUB_ERROR_BODY_LIMIT_CHARS
    _assert_terminal_safe(body)
    _assert_terminal_safe(str(exc_info.value))


def test_retryable_success_envelope_diagnostic_is_safe(monkeypatch) -> None:
    hostile_message = (
        "Base branch was modified\x1b[31m" + TOKEN + "\u202e\ud800" + "x" * 6000
    )
    response_body = json.dumps({"message": hostile_message}).encode("utf-8")

    class _Response:
        status = 200
        headers: dict[str, str] = {}

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def read(self, size: int = -1) -> bytes:
            return response_body if size < 0 else response_body[:size]

    monkeypatch.setattr(transport, "urlopen", lambda *_a, **_k: _Response())
    with pytest.raises(transport.RestUnprocessableError) as exc_info:
        transport.request_with_retry(
            transport.RestRequest(method="PUT", path="/repos/o/r/pulls/1/merge"),
            token=TOKEN,
            max_attempts=1,
        )

    body = exc_info.value.body or ""
    assert len(body) == GITHUB_ERROR_BODY_LIMIT_CHARS
    _assert_terminal_safe(body)
    _assert_terminal_safe(str(exc_info.value))
