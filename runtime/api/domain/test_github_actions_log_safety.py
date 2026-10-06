"""Adversarial bounds for GitHub Actions per-job log reads."""

from __future__ import annotations

import urllib.error

import pytest

from yoke_core.domain import github_actions_logs
from yoke_core.domain.gh_rest_transport import RestAuthError, RestNetworkError


class _RecordingReader:
    def __init__(self, payload: bytes, *, headers: dict[str, str] | None = None):
        self.payload = payload
        self.headers = headers or {}
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


def test_job_log_fetch_accepts_exact_boundary_and_uses_sentinel(
    monkeypatch,
) -> None:
    monkeypatch.setattr(github_actions_logs, "GITHUB_ACTIONS_JOB_LOG_LIMIT_BYTES", 8)
    response = _RecordingReader(b"12345678")
    monkeypatch.setattr(
        github_actions_logs, "urlopen", lambda *_args, **_kwargs: response
    )

    result = github_actions_logs.fetch_job_log("o/r", 1, token="ghs_x")

    assert result == "12345678"
    assert response.read_sizes == [9]


def test_job_log_fetch_rejects_overflow_sentinel(monkeypatch) -> None:
    monkeypatch.setattr(github_actions_logs, "GITHUB_ACTIONS_JOB_LOG_LIMIT_BYTES", 8)
    response = _RecordingReader(b"123456789")
    monkeypatch.setattr(
        github_actions_logs, "urlopen", lambda *_args, **_kwargs: response
    )

    with pytest.raises(github_actions_logs.JobLogTooLargeError):
        github_actions_logs.fetch_job_log("o/r", 1, token="ghs_x")

    assert response.read_sizes == [9]


def test_content_length_oversize_fails_before_read(monkeypatch) -> None:
    monkeypatch.setattr(github_actions_logs, "GITHUB_ACTIONS_JOB_LOG_LIMIT_BYTES", 8)
    response = _RecordingReader(b"ignored", headers={"content-length": "9"})
    monkeypatch.setattr(
        github_actions_logs, "urlopen", lambda *_args, **_kwargs: response
    )

    with pytest.raises(github_actions_logs.JobLogTooLargeError):
        github_actions_logs.fetch_job_log("o/r", 1, token="ghs_x")

    assert response.read_sizes == []


def test_http_error_is_bounded_classified_and_token_scrubbed(monkeypatch) -> None:
    token = "ghs_log_secret"
    monkeypatch.setattr(github_actions_logs, "GITHUB_SMALL_RESPONSE_LIMIT_BYTES", 256)
    body = _RecordingReader(
        f"prefix{token}suffix repeated={token}:{token}".encode("utf-8")
    )
    error = urllib.error.HTTPError("https://api.github.com/x", 401, token, {}, body)

    def fail(*_args, **_kwargs):
        raise error

    monkeypatch.setattr(github_actions_logs, "urlopen", fail)

    with pytest.raises(RestAuthError) as exc_info:
        github_actions_logs.fetch_job_log("o/r", 1, token=token)

    rendered = f"{exc_info.value} {exc_info.value.body}"
    assert token not in rendered
    assert body.read_sizes == [257]
    assert exc_info.value.status == 401
    assert exc_info.value.__cause__ is None


def test_oversized_http_error_preserves_status_classification(monkeypatch) -> None:
    monkeypatch.setattr(github_actions_logs, "GITHUB_SMALL_RESPONSE_LIMIT_BYTES", 8)
    body = _RecordingReader(b"123456789")
    error = urllib.error.HTTPError("https://api.github.com/x", 403, "secret", {}, body)
    monkeypatch.setattr(
        github_actions_logs,
        "urlopen",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(error),
    )

    with pytest.raises(RestAuthError) as exc_info:
        github_actions_logs.fetch_job_log("o/r", 1, token="secret")

    assert exc_info.value.status == 403
    assert body.read_sizes == [9]


def test_network_reason_is_detail_free(monkeypatch) -> None:
    token = "ghs_network_secret"

    def fail(*_args, **_kwargs):
        raise urllib.error.URLError(f"upstream echoed {token}")

    monkeypatch.setattr(github_actions_logs, "urlopen", fail)
    monkeypatch.setattr(github_actions_logs, "sleep", lambda _seconds: None)

    with pytest.raises(RestNetworkError) as exc_info:
        github_actions_logs.fetch_job_log("o/r", 1, token=token)

    assert token not in str(exc_info.value)
    assert exc_info.value.__cause__ is None


@pytest.mark.parametrize("failure_type", [TimeoutError, OSError])
def test_direct_network_failures_are_normalized(monkeypatch, failure_type) -> None:
    token = "ghs_direct_network_secret"

    def fail(*_args, **_kwargs):
        raise failure_type(token)

    monkeypatch.setattr(github_actions_logs, "urlopen", fail)
    monkeypatch.setattr(github_actions_logs, "sleep", lambda _seconds: None)

    with pytest.raises(RestNetworkError) as exc_info:
        github_actions_logs.fetch_job_log("o/r", 1, token=token)

    assert token not in str(exc_info.value)
    assert exc_info.value.__cause__ is None
