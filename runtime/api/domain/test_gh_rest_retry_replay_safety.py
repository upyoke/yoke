"""Replay-safety coverage for ambiguous GitHub REST failures."""

from __future__ import annotations

import http.client
import urllib.error

import pytest

from yoke_core.domain import gh_rest_transport as transport


_UNSAFE_POST_PATHS = (
    "/repos/o/r/issues",
    "/repos/o/r/issues/1/comments",
    "/repos/o/r/pulls",
    "/repos/o/r/actions/workflows/deploy.yml/dispatches",
)


class _Response:
    status = 200
    headers: dict[str, str] = {}

    def __init__(self, body: bytes = b"{}") -> None:
        self.body = body

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def read(self, size: int = -1) -> bytes:
        return self.body if size < 0 else self.body[:size]


class _BrokenResponse(_Response):
    def read(self, size: int = -1) -> bytes:
        del size
        raise http.client.IncompleteRead(b"partial", 10)


@pytest.fixture(autouse=True)
def _no_backoff(monkeypatch):
    monkeypatch.setattr(transport, "sleep", lambda _seconds: None)
    monkeypatch.delenv(transport._FAKE_DIR_ENV, raising=False)


@pytest.mark.parametrize("path", _UNSAFE_POST_PATHS)
def test_unsafe_posts_do_not_replay_network_failures(monkeypatch, path) -> None:
    calls = 0

    def unavailable_then_success(*_args, **_kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise urllib.error.URLError("ambiguous failure")
        return _Response()

    monkeypatch.setattr(transport, "urlopen", unavailable_then_success)
    with pytest.raises(transport.RestNetworkError):
        transport.request_with_retry(
            transport.RestRequest(method="POST", path=path, body={}),
            token="ghs_secret",
        )

    assert calls == 1


@pytest.mark.parametrize("path", _UNSAFE_POST_PATHS)
def test_unsafe_posts_do_not_replay_response_read_failures(monkeypatch, path) -> None:
    calls = 0

    def broken_then_success(*_args, **_kwargs):
        nonlocal calls
        calls += 1
        return _BrokenResponse() if calls == 1 else _Response()

    monkeypatch.setattr(transport, "urlopen", broken_then_success)
    with pytest.raises(transport.RestNetworkError):
        transport.request_with_retry(
            transport.RestRequest(method="POST", path=path, body={}),
            token="ghs_secret",
        )

    assert calls == 1


@pytest.mark.parametrize(
    "rest_request",
    (
        transport.RestRequest(method="GET", path="/repos/o/r"),
        transport.RestRequest(
            method="PUT",
            path="/repos/o/r/issues/1/labels",
            body={"labels": ["bug"]},
        ),
        transport.RestRequest(
            method="PATCH",
            path="/repos/o/r/issues/1",
            body={"state": "closed"},
            replay_safe=True,
        ),
    ),
)
def test_registered_safe_operations_replay_transient_failures(
    monkeypatch,
    rest_request,
) -> None:
    calls = 0

    def unavailable_then_success(*_args, **_kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise urllib.error.URLError("transient failure")
        return _Response()

    monkeypatch.setattr(transport, "urlopen", unavailable_then_success)
    response = transport.request_with_retry(rest_request, token="ghs_secret")

    assert response.body == {}
    assert calls == 2


def test_patch_requires_explicit_replay_registration(monkeypatch) -> None:
    calls = 0

    def unavailable(*_args, **_kwargs):
        nonlocal calls
        calls += 1
        raise urllib.error.URLError("ambiguous failure")

    monkeypatch.setattr(transport, "urlopen", unavailable)
    with pytest.raises(transport.RestNetworkError):
        transport.request_with_retry(
            transport.RestRequest(
                method="PATCH",
                path="/repos/o/r/issues/1",
                body={"state": "closed"},
            ),
            token="ghs_secret",
        )

    assert calls == 1


def test_reconciled_post_can_explicitly_enable_replay(monkeypatch) -> None:
    calls = 0

    def unavailable_then_success(*_args, **_kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise urllib.error.URLError("transient failure")
        return _Response()

    monkeypatch.setattr(transport, "urlopen", unavailable_then_success)
    response = transport.request_with_retry(
        transport.RestRequest(
            method="POST",
            path="/graphql",
            body={"query": "query { viewer { login } }"},
            replay_safe=True,
        ),
        token="ghs_secret",
    )

    assert response.body == {}
    assert calls == 2
