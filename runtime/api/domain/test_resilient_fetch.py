"""Tests for the shared external-artifact fetch gateway."""

from __future__ import annotations

import hashlib
import os
import subprocess
import sys
import urllib.error
from pathlib import Path

import pytest

from yoke_core import resilient_fetch


URL = "https://artifacts.example.test/release.tar.gz"


def test_gateway_imports_before_project_dependencies_are_installed() -> None:
    repo_root = Path(__file__).resolve().parents[3]
    env = os.environ.copy()
    env["PYTHONPATH"] = str(repo_root / "packages/yoke-core/src")

    completed = subprocess.run(
        [sys.executable, "-S", "-m", "yoke_core.resilient_fetch"],
        cwd=repo_root,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr


class _Response:
    def __init__(self, body: bytes, *, content_length: int | None = None) -> None:
        self.body = body
        self.headers = {}
        if content_length is not None:
            self.headers["Content-Length"] = str(content_length)

    def __enter__(self):
        return self

    def __exit__(self, *_args) -> None:
        return None

    def read(self, limit: int | None = None) -> bytes:
        return self.body if limit is None else self.body[:limit]


def _bind_transport(monkeypatch, effects):
    calls = []
    pending = iter(effects)

    def opener(request, *, timeout):
        calls.append((request.full_url, timeout))
        effect = next(pending)
        if isinstance(effect, BaseException):
            raise effect
        return effect

    sleeps: list[float] = []
    monkeypatch.setattr(resilient_fetch, "urlopen", opener)
    monkeypatch.setattr(resilient_fetch, "sleep", sleeps.append)
    return calls, sleeps


def test_connection_drops_twice_then_records_third_attempt(monkeypatch) -> None:
    body = b"verified artifact"
    calls, sleeps = _bind_transport(
        monkeypatch,
        [
            urllib.error.URLError("connection dropped"),
            TimeoutError("timed out"),
            _Response(body, content_length=len(body)),
        ],
    )

    result = resilient_fetch.fetch_bytes(URL)

    assert result.body == body
    assert result.attempts == 3
    assert calls == [(URL, 120.0), (URL, 120.0), (URL, 120.0)]
    assert sleeps == [15.0, 60.0]


def test_server_error_retries(monkeypatch) -> None:
    unavailable = urllib.error.HTTPError(URL, 503, "unavailable", {}, None)
    _calls, sleeps = _bind_transport(
        monkeypatch, [unavailable, _Response(b"ok", content_length=2)]
    )

    result = resilient_fetch.fetch_bytes(URL)

    assert result.attempts == 2
    assert sleeps == [15.0]


def test_client_error_is_permanent_and_names_attempts(monkeypatch) -> None:
    missing = urllib.error.HTTPError(URL, 404, "missing", {}, None)
    calls, sleeps = _bind_transport(monkeypatch, [missing])

    with pytest.raises(resilient_fetch.FetchError) as raised:
        resilient_fetch.fetch_bytes(URL)

    assert raised.value.attempts == 1
    assert raised.value.retryable is False
    assert URL in str(raised.value)
    assert "1 attempt" in str(raised.value)
    assert len(calls) == 1
    assert sleeps == []


def test_checksum_mismatch_is_not_retried(monkeypatch) -> None:
    calls, sleeps = _bind_transport(
        monkeypatch, [_Response(b"wrong", content_length=5)]
    )

    with pytest.raises(resilient_fetch.FetchVerificationError, match="sha256"):
        resilient_fetch.fetch_bytes(URL, expected_sha256="0" * 64)

    assert len(calls) == 1
    assert sleeps == []


def test_truncated_content_length_is_not_retried(monkeypatch) -> None:
    calls, sleeps = _bind_transport(
        monkeypatch, [_Response(b"short", content_length=500)]
    )

    with pytest.raises(
        resilient_fetch.FetchVerificationError, match="Content-Length 500"
    ):
        resilient_fetch.fetch_bytes(URL)

    assert len(calls) == 1
    assert sleeps == []


def test_file_is_published_only_after_verification(monkeypatch, tmp_path: Path) -> None:
    destination = tmp_path / "release.tar.gz"
    destination.write_bytes(b"existing")
    body = b"new artifact"
    _bind_transport(monkeypatch, [_Response(body, content_length=len(body))])

    result = resilient_fetch.fetch_file(
        URL,
        destination,
        expected_sha256=hashlib.sha256(body).hexdigest(),
    )

    assert result.attempts == 1
    assert destination.read_bytes() == body
