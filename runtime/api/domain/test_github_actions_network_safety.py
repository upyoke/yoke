"""Operation-deadline and diagnostic safety for GitHub Actions log fetches."""

from __future__ import annotations

import unicodedata
import urllib.error

import pytest

from yoke_core.domain import github_actions_logs
from yoke_core.domain.gh_rest_transport import RestAuthError, RestNetworkError


class _Reader:
    headers: dict[str, str] = {}

    def __init__(self, payload: bytes) -> None:
        self.payload = payload

    def read(self, size: int = -1) -> bytes:
        return self.payload if size < 0 else self.payload[:size]

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def close(self) -> None:
        return None


class _Clock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def test_http_error_diagnostic_neutralizes_controls(monkeypatch) -> None:
    token = "ghs_log_secret"
    hostile = f"denied\x1b]8;;https://evil.example\x07{token}\u202e"
    error = urllib.error.HTTPError(
        "https://api.github.com/x",
        401,
        token,
        {},
        _Reader(hostile.encode("utf-8")),
    )

    def reject(*_args, **_kwargs):
        raise error

    monkeypatch.setattr(github_actions_logs, "urlopen", reject)
    with pytest.raises(RestAuthError) as exc_info:
        github_actions_logs.fetch_failed_log_zip("o/r", 1, token=token)

    rendered = f"{exc_info.value} {exc_info.value.body}"
    assert token not in rendered
    assert not any(
        unicodedata.category(character) in {"Cc", "Cf", "Cs"} for character in rendered
    )


def test_retries_share_one_actions_log_deadline(monkeypatch) -> None:
    clock = _Clock()
    timeouts: list[float] = []
    calls = 0

    def open_next(_request, timeout):
        nonlocal calls
        calls += 1
        timeouts.append(timeout)
        if calls == 1:
            raise urllib.error.URLError("transient")
        return _Reader(b"zip")

    monkeypatch.setattr(github_actions_logs, "_FETCH_TIMEOUT_SECONDS", 10.0)
    monkeypatch.setattr(github_actions_logs.github_response_safety, "monotonic", clock)
    monkeypatch.setattr(github_actions_logs, "sleep", clock.advance)
    monkeypatch.setattr(github_actions_logs, "urlopen", open_next)

    assert github_actions_logs.fetch_failed_log_zip("o/r", 1, token="ghs_x") == b"zip"
    assert timeouts == pytest.approx([10.0, 5.0])


def test_actions_log_backoff_cannot_cross_deadline(monkeypatch) -> None:
    clock = _Clock()
    sleeps: list[float] = []
    calls = 0

    def unavailable(*_args, **_kwargs):
        nonlocal calls
        calls += 1
        raise urllib.error.URLError("transient")

    monkeypatch.setattr(github_actions_logs, "_FETCH_TIMEOUT_SECONDS", 4.0)
    monkeypatch.setattr(github_actions_logs.github_response_safety, "monotonic", clock)
    monkeypatch.setattr(github_actions_logs, "sleep", sleeps.append)
    monkeypatch.setattr(github_actions_logs, "urlopen", unavailable)

    with pytest.raises(RestNetworkError, match="operation exceeded"):
        github_actions_logs.fetch_failed_log_zip("o/r", 1, token="ghs_x")

    assert calls == 1
    assert sleeps == []
