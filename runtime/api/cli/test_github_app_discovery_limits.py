"""Whole-operation safety budgets for GitHub App access discovery."""

from __future__ import annotations

import json
import urllib.error

import pytest

from runtime.api.cli.test_github_app_machine_connection import (
    _Response,
    _permissions,
)
from yoke_cli.config import github_app_user_api, github_machine_access
from yoke_contracts import github_app_tokens


def test_installation_discovery_has_a_pagination_safety_cap() -> None:
    installation = {
        "id": 123,
        "app_id": 123,
        "app_slug": "yoke-local",
        "account": {"id": 9, "login": "octo-org", "type": "Organization"},
        "repository_selection": "selected",
        "permissions": _permissions(),
        "suspended_at": None,
    }

    def endless_pages(request, timeout):
        if request.full_url.endswith("/user"):
            return _Response(
                {"id": 42, "login": "octocat"}, url=request.full_url,
            )
        return _Response(
            {"installations": [installation] * 100}, url=request.full_url,
        )

    with pytest.raises(
        github_app_user_api.GitHubAppUserApiError,
        match="exceeded 100 pages",
    ):
        github_app_user_api.discover_access(
            api_url="https://api.github.com",
            access_token="access-secret",
            opener=endless_pages,
        )


def test_repository_page_larger_than_64k_is_valid_below_collection_cap() -> None:
    repositories = [
        {
            "id": index + 1,
            "full_name": f"octo-org/repository-{index}",
            "default_branch": "main",
            "private": True,
            "description": "x" * 1_000,
        }
        for index in range(100)
    ]
    assert len(json.dumps({"repositories": repositories})) > 64 * 1024

    def opener(request, timeout):
        url = request.full_url
        if url.endswith("/user"):
            return _Response({"id": 42, "login": "octocat"}, url=url)
        if "/user/installations?" in url:
            return _Response({"installations": [{
                "id": 123,
                "app_id": 123,
                "app_slug": "yoke-local",
                "account": {"id": 9, "login": "octo-org", "type": "Organization"},
                "repository_selection": "selected",
                "permissions": _permissions(),
                "suspended_at": None,
            }]}, url=url)
        if "/repositories?per_page=100&page=1" in url:
            return _Response({"repositories": repositories}, url=url)
        if "/repositories?per_page=100&page=2" in url:
            return _Response({"repositories": []}, url=url)
        raise AssertionError(url)

    snapshot = github_app_user_api.discover_access(
        api_url="https://api.github.com",
        access_token="access-secret",
        opener=opener,
    )

    assert len(snapshot["repositories"]) == 100


def test_discovery_rejects_response_over_collection_cap() -> None:
    class _OversizedResponse(_Response):
        def read(self, size: int = -1) -> bytes:
            return b"x" * min(
                size,
                github_app_tokens.GITHUB_API_RESPONSE_MAX_BYTES + 1,
            )

    with pytest.raises(
        github_app_user_api.GitHubAppUserApiError,
        match="response is too large",
    ):
        github_app_user_api.discover_access(
            api_url="https://api.github.com",
            access_token="access-secret",
            opener=lambda request, timeout: _OversizedResponse(
                {}, url=request.full_url,
            ),
        )


def test_discovery_enforces_one_request_budget_across_installations() -> None:
    installation = {
        "app_id": 123,
        "app_slug": "yoke-local",
        "account": {"id": 9, "login": "octo-org", "type": "Organization"},
        "repository_selection": "selected",
        "permissions": _permissions(),
        "suspended_at": None,
    }

    def opener(request, timeout):
        url = request.full_url
        if url.endswith("/user"):
            return _Response({"id": 42, "login": "octocat"}, url=url)
        if "/user/installations?" in url:
            page = int(url.rsplit("page=", 1)[1])
            if page <= 3:
                return _Response({"installations": [
                    {**installation, "id": (page - 1) * 100 + index + 1}
                    for index in range(100)
                ]}, url=url)
            return _Response({"installations": []}, url=url)
        if "/repositories?" in url:
            return _Response({"repositories": []}, url=url)
        raise AssertionError(url)

    with pytest.raises(
        github_app_user_api.GitHubAppUserApiError,
        match="total request/deadline budget",
    ):
        github_app_user_api.discover_access(
            api_url="https://api.github.com",
            access_token="access-secret",
            opener=opener,
        )


def test_discovery_invalid_utf8_is_a_typed_error() -> None:
    class _RawResponse(_Response):
        def read(self, size: int = -1) -> bytes:
            return b"\xff"

    with pytest.raises(github_app_user_api.GitHubAppUserApiError, match="not JSON"):
        github_app_user_api.discover_access(
            api_url="https://api.github.com",
            access_token="access-secret",
            opener=lambda request, timeout: _RawResponse(
                {}, url=request.full_url,
            ),
        )


def test_discovery_transport_reason_redacts_access_token() -> None:
    with pytest.raises(github_app_user_api.GitHubAppUserApiError) as caught:
        github_app_user_api.discover_access(
            api_url="https://api.github.com",
            access_token="access-secret",
            opener=lambda request, timeout: (_ for _ in ()).throw(
                urllib.error.URLError("refused access-secret")
            ),
        )
    assert "access-secret" not in str(caught.value)


@pytest.mark.parametrize("failure", [
    TimeoutError("socket detail must not leak"),
    OSError("platform detail must not leak"),
])
def test_discovery_wraps_direct_transport_errors_without_details(
    failure: Exception,
) -> None:
    with pytest.raises(github_app_user_api.GitHubAppUserApiError) as caught:
        github_app_user_api.discover_access(
            api_url="https://api.github.com",
            access_token="access-secret",
            opener=lambda request, timeout: (_ for _ in ()).throw(failure),
        )
    message = str(caught.value)
    assert "could not be reached" in message
    assert "must not leak" not in message


def test_unauthorized_retries_share_one_operation_deadline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clock = [0.0]
    calls = 0

    def unauthorized(**kwargs):
        nonlocal calls
        calls += 1
        raise github_app_user_api.GitHubAppUserApiError(
            "not ready", status=401,
        )

    monkeypatch.setattr(
        github_machine_access.github_app_user_api,
        "discover_access",
        unauthorized,
    )
    sleeps: list[float] = []

    def sleep(seconds: float) -> None:
        sleeps.append(seconds)
        clock[0] += seconds

    with pytest.raises(github_app_user_api.GitHubAppUserApiError):
        github_machine_access.discover_access_with_unauthorized_retry(
            api_url="https://api.github.com",
            access_token="access-secret",
            opener=None,
            sleep=sleep,
            monotonic=lambda: clock[0],
            deadline_seconds=2.5,
        )

    assert calls == 2
    assert sleeps == [1.0]
