"""Security-boundary tests for GitHub App configuration and user verification."""

from __future__ import annotations

from datetime import datetime, timezone
import json
import urllib.parse

import pytest

from yoke_contracts.github_origin import (
    GitHubApiOriginError,
    validate_github_api_endpoint,
    validate_github_web_endpoint,
)
from yoke_core.domain import github_app_user_verification as verification
from yoke_core.domain.github_api_transport import _ExactOriginRedirectHandler
from yoke_core.domain.github_app_token_models import UserAccessToken
from yoke_core.domain.github_app_user_verification import (
    GitHubUserVerificationError,
    verify_project_github_binding,
)


class _Response:
    def __init__(self, body, url: str) -> None:
        self._body = json.dumps(body).encode("utf-8")
        self._url = url

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        return False

    def geturl(self) -> str:
        return self._url

    def read(self, size: int = -1) -> bytes:
        return self._body if size < 0 else self._body[:size]


def _verification_opener(seen):
    def open_request(request, timeout):
        seen.append(request)
        path = urllib.parse.urlsplit(request.full_url).path
        api_path = path.removeprefix("/api/v3")
        if api_path == "/user":
            body = {"id": 77, "login": "octocat"}
        elif api_path == "/user/installations":
            body = {
                "installations": [
                    {
                        "id": 12345,
                        "account": {
                            "id": 9988,
                            "login": "Example-Org",
                            "type": "Organization",
                        },
                        "repository_selection": "selected",
                        "permissions": {"issues": "write", "checks": "read"},
                        "suspended_at": None,
                    }
                ],
            }
        else:
            assert api_path == "/user/installations/12345/repositories"
            body = {
                "repositories": [
                    {
                        "id": 4567,
                        "full_name": "Example-Org/Buzz",
                        "default_branch": "trunk",
                        "owner": {"id": 9988},
                    }
                ],
            }
        return _Response(body, request.full_url)

    return open_request


def test_user_token_canonicalizes_installation_and_repository_metadata() -> None:
    seen = []

    verified = verify_project_github_binding(
        installation_id="12345",
        repository_id="4567",
        expected_github_repo="example-org/buzz",
        expected_api_url="https://github.example/api/v3",
        github_user_access_token="github-user-token",
        endpoint=validate_github_api_endpoint("https://github.example/api/v3"),
        opener=_verification_opener(seen),
    )

    assert verified.account_id == "9988"
    assert verified.account_login == "Example-Org"
    assert verified.github_repo == "Example-Org/Buzz"
    assert verified.default_branch == "trunk"
    assert verified.api_url == "https://github.example/api/v3"
    assert verified.permissions == {"issues": "write", "checks": "read"}
    assert [urllib.parse.urlsplit(req.full_url).path for req in seen] == [
        "/api/v3/user",
        "/api/v3/user/installations",
        "/api/v3/user/installations/12345/repositories",
    ]
    assert all(
        req.get_header("Authorization") == "Bearer github-user-token" for req in seen
    )


def test_user_token_preserves_suspended_installation_for_unavailable_binding() -> None:
    def suspended_open(request, timeout):
        response = _verification_opener([])(request, timeout)
        path = urllib.parse.urlsplit(request.full_url).path
        if path.endswith("/user/installations"):
            body = json.loads(response.read())
            body["installations"][0]["suspended_at"] = "2026-07-09T12:00:00Z"
            return _Response(body, request.full_url)
        return response

    verified = verify_project_github_binding(
        installation_id="12345",
        repository_id="4567",
        expected_github_repo="example-org/buzz",
        expected_api_url="https://api.github.com",
        github_user_access_token="github-user-token",
        endpoint=validate_github_api_endpoint("https://api.github.com"),
        opener=suspended_open,
    )

    assert verified.installation_status == "suspended"


def test_user_token_rejects_repository_id_name_mismatch() -> None:
    with pytest.raises(GitHubUserVerificationError, match="not another/repo"):
        verify_project_github_binding(
            installation_id="12345",
            repository_id="4567",
            expected_github_repo="another/repo",
            expected_api_url="https://api.github.com",
            github_user_access_token="github-user-token",
            endpoint=validate_github_api_endpoint("https://api.github.com"),
            opener=_verification_opener([]),
        )


def test_user_token_is_not_sent_when_expected_api_base_mismatches() -> None:
    called = False

    def unexpected_open(request, timeout):
        nonlocal called
        called = True
        raise AssertionError("token-bearing request must not be issued")

    with pytest.raises(GitHubUserVerificationError, match="does not match"):
        verify_project_github_binding(
            installation_id="12345",
            repository_id="4567",
            expected_github_repo="example-org/buzz",
            expected_api_url="https://github-other.example/api/v3",
            github_user_access_token="github-user-token",
            endpoint=validate_github_api_endpoint("https://github.example/api/v3"),
            opener=unexpected_open,
        )

    assert called is False


def test_pagination_continues_after_malformed_entry_on_full_page() -> None:
    endpoint = validate_github_api_endpoint("https://api.github.com")

    def paged_open(request, timeout):
        page = urllib.parse.parse_qs(urllib.parse.urlsplit(request.full_url).query)[
            "page"
        ][0]
        if page == "1":
            entries = [{"id": value} for value in range(1, 100)] + ["malformed"]
        else:
            entries = [{"id": 999}]
        return _Response({"repositories": entries}, request.full_url)

    found = verification._find_paginated(
        endpoint,
        "/repositories",
        collection_key="repositories",
        selected_id=999,
        token="github-user-token",
        opener=paged_open,
        timeout_seconds=1,
    )

    assert found == {"id": 999}


@pytest.mark.parametrize(
    "value",
    [
        "http://api.github.com",
        "https://user@example.test/api/v3",
        "https://example.test/api/v3?redirect=https://evil.test",
        "https://example.test/api/../v3",
    ],
)
def test_api_endpoint_rejects_unsafe_origins(value: str) -> None:
    with pytest.raises(GitHubApiOriginError):
        validate_github_api_endpoint(value)


def test_web_endpoint_supports_exact_ghes_origin() -> None:
    endpoint = validate_github_web_endpoint("https://github.example")
    assert endpoint.origin == "https://github.example"
    assert endpoint.url("/login/device") == "https://github.example/login/device"


def test_authorized_redirect_cannot_cross_configured_origin() -> None:
    handler = _ExactOriginRedirectHandler(
        validate_github_api_endpoint("https://github.example/api/v3")
    )

    with pytest.raises(GitHubApiOriginError, match="crossed"):
        handler.redirect_request(
            None,
            None,
            302,
            "Found",
            {},
            "https://attacker.example/collect",
        )


def test_user_access_token_repr_hides_access_and_refresh_tokens() -> None:
    now = datetime(2026, 7, 9, tzinfo=timezone.utc)
    token = UserAccessToken(
        access_token="github-access-secret",
        expires_at=now,
        refresh_token="github-refresh-secret",
        refresh_expires_at=now,
    )

    rendered = repr(token)
    assert "github-access-secret" not in rendered
    assert "github-refresh-secret" not in rendered
