"""Whole-open compatibility and redirect-policy tests for GitHub calls."""

from __future__ import annotations

import urllib.request

import pytest

from yoke_contracts.github_origin import (
    GitHubApiOriginError,
    validate_github_api_endpoint,
)
from yoke_core.domain import github_api_transport


class _MutableClock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


class _Response:
    def __init__(self, url: str) -> None:
        self.url = url
        self.closed = False

    def geturl(self) -> str:
        return self.url

    def close(self) -> None:
        self.closed = True


def _request() -> urllib.request.Request:
    return urllib.request.Request("https://api.github.com/user", method="GET")


def _endpoint():
    return validate_github_api_endpoint("https://api.github.com")


def test_injected_replay_safe_opener_preserves_timeout_and_response() -> None:
    seen = []
    response = _Response(_request().full_url)

    def opener(request, timeout):
        seen.append((request.full_url, timeout))
        return response

    selected = github_api_transport.open_same_origin_deadline(
        _request(),
        endpoint=_endpoint(),
        deadline=1.0,
        replay_safe=True,
        opener=opener,
        clock=lambda: 0.0,
    )

    assert selected is response
    assert seen == [("https://api.github.com/user", 1.0)]


def test_injected_unsafe_opener_closes_late_response() -> None:
    clock = _MutableClock()
    response = _Response(_request().full_url)

    def opener(_request, timeout):
        assert timeout == pytest.approx(1.0)
        clock.advance(1.1)
        return response

    with pytest.raises(github_api_transport.ResponseOpenDeadlineError):
        github_api_transport.open_same_origin_deadline(
            _request(),
            endpoint=_endpoint(),
            deadline=1.0,
            replay_safe=False,
            opener=opener,
            clock=clock,
        )

    assert response.closed is True


@pytest.mark.parametrize(
    "reject_redirects,handler_type",
    (
        (False, github_api_transport._ExactOriginRedirectHandler),
        (True, github_api_transport._RejectRedirectHandler),
    ),
)
def test_default_unsafe_open_uses_caller_owned_redirect_policy(
    monkeypatch,
    reject_redirects,
    handler_type,
) -> None:
    seen = {}
    response = _Response(_request().full_url)
    monkeypatch.setattr(github_api_transport, "block_live_test_call", lambda *_a: None)

    def caller_owned(request, *, deadline, handlers, clock):
        seen.update(
            request=request,
            deadline=deadline,
            handlers=handlers,
            clock=clock,
        )
        return response

    monkeypatch.setattr(
        github_api_transport,
        "open_https_caller_owned",
        caller_owned,
    )
    selected = github_api_transport.open_same_origin_deadline(
        _request(),
        endpoint=_endpoint(),
        deadline=1.0,
        replay_safe=False,
        reject_redirects=reject_redirects,
        clock=lambda: 0.0,
    )

    assert selected is response
    assert isinstance(seen["handlers"][0], handler_type)


def test_exact_origin_handler_allows_same_origin_and_refuses_cross_origin() -> None:
    handler = github_api_transport._ExactOriginRedirectHandler(_endpoint())
    source = _request()

    same_origin = handler.redirect_request(
        source,
        None,
        302,
        "Found",
        {},
        "https://api.github.com/octocat",
    )

    assert same_origin is not None
    assert same_origin.full_url == "https://api.github.com/octocat"
    with pytest.raises(GitHubApiOriginError):
        handler.redirect_request(
            source,
            None,
            302,
            "Found",
            {},
            "https://attacker.example/collect",
        )


def test_default_replay_safe_open_uses_fenced_worker(monkeypatch) -> None:
    response = _Response(_request().full_url)
    seen = {}
    monkeypatch.setattr(github_api_transport, "block_live_test_call", lambda *_a: None)

    class _SafeOpener:
        def open(self, *_args, **_kwargs):
            raise AssertionError("worker seam should receive, not invoke, opener")

    monkeypatch.setattr(
        github_api_transport.urllib.request,
        "build_opener",
        lambda *_handlers: _SafeOpener(),
    )

    def replay_safe(request, *, opener, deadline, clock):
        seen.update(
            request=request,
            opener=opener,
            deadline=deadline,
            clock=clock,
        )
        return response

    monkeypatch.setattr(github_api_transport, "open_replay_safe", replay_safe)
    selected = github_api_transport.open_same_origin_deadline(
        _request(),
        endpoint=_endpoint(),
        deadline=1.0,
        replay_safe=True,
        clock=lambda: 0.0,
    )

    assert selected is response
    assert seen["deadline"] == 1.0
    assert callable(seen["opener"])
