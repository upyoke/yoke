"""Whole-operation deadline coverage for retried GitHub REST requests."""

from __future__ import annotations

import urllib.error

import pytest

from yoke_core.domain import gh_rest_transport as transport
from yoke_core.domain import github_response_safety


class _MutableClock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


class _Response:
    status = 200
    headers: dict[str, str] = {}

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def read(self, size: int = -1) -> bytes:
        body = b"{}"
        return body if size < 0 else body[:size]


@pytest.fixture(autouse=True)
def _isolate_transport(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(transport._FAKE_DIR_ENV, raising=False)
    monkeypatch.delenv(transport.GITHUB_APP_API_URL_ENV, raising=False)


def test_retries_share_one_deadline_with_backoff(monkeypatch) -> None:
    clock = _MutableClock()
    timeouts: list[float] = []
    calls = 0

    def opener(_request, timeout):
        nonlocal calls
        calls += 1
        timeouts.append(timeout)
        if calls == 1:
            raise urllib.error.URLError("transient")
        return _Response()

    monkeypatch.setattr(github_response_safety, "monotonic", clock)
    monkeypatch.setattr(transport, "urlopen", opener)
    monkeypatch.setattr(transport, "sleep", clock.advance)

    response = transport.request_with_retry(
        transport.RestRequest(method="GET", path="/user"),
        token="ghs_secret",
        timeout_seconds=10.0,
        max_attempts=2,
    )

    assert response.body == {}
    assert timeouts == pytest.approx([10.0, 5.0])
    assert clock.now == 5.0


def test_retry_backoff_cannot_cross_operation_deadline(monkeypatch) -> None:
    clock = _MutableClock()
    sleeps: list[float] = []
    calls = 0

    def opener(_request, timeout):
        nonlocal calls
        del timeout
        calls += 1
        raise urllib.error.URLError("transient")

    monkeypatch.setattr(github_response_safety, "monotonic", clock)
    monkeypatch.setattr(transport, "urlopen", opener)
    monkeypatch.setattr(transport, "sleep", sleeps.append)

    with pytest.raises(
        transport.RestNetworkError,
        match="operation exceeded the time limit",
    ):
        transport.request_with_retry(
            transport.RestRequest(method="GET", path="/user"),
            token="ghs_secret",
            timeout_seconds=4.0,
            max_attempts=2,
        )

    assert calls == 1
    assert sleeps == []


@pytest.mark.parametrize("timeout", [0, -1, float("inf"), float("nan")])
def test_operation_deadline_rejects_non_positive_or_non_finite_timeout(
    monkeypatch,
    timeout,
) -> None:
    monkeypatch.setattr(
        transport,
        "urlopen",
        lambda *_args, **_kwargs: pytest.fail("network must not be called"),
    )

    with pytest.raises(transport.RestTransportError, match="positive and finite"):
        transport.request_with_retry(
            transport.RestRequest(method="GET", path="/user"),
            token="ghs_secret",
            timeout_seconds=timeout,
        )
