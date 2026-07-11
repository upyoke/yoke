"""Response and timeout bounds for GitHub App binding trust calls."""

from __future__ import annotations

import urllib.parse

import pytest

from runtime.api.domain.github_app_server_verification_test_support import (
    FakeGitHubResponse,
    github_app_control_plane_config,
    github_app_installation_payload,
)
from yoke_core.domain.github_app_identity import GitHubAppIdentityVerificationError
from yoke_core.domain.github_app_identity_verification import (
    fetch_authenticated_app_identity,
)
from yoke_core.domain.github_app_server_installation import (
    GitHubServerInstallationVerificationError,
    ServerVerifiedInstallation,
    fetch_server_app_installation,
)
from yoke_core.domain.github_app_user_verification import (
    GitHubUserVerificationError,
    verify_project_github_binding,
)
from yoke_core.domain.github_app_verification_response import (
    GITHUB_APP_COLLECTION_RESPONSE_LIMIT_BYTES,
    GITHUB_APP_VERIFICATION_RESPONSE_LIMIT_BYTES,
)


def test_server_installation_response_is_size_bounded():
    oversized = b"{" + b"x" * GITHUB_APP_VERIFICATION_RESPONSE_LIMIT_BYTES

    def opener(request, timeout):
        del timeout
        return FakeGitHubResponse(oversized, request.full_url)

    with pytest.raises(GitHubServerInstallationVerificationError, match="size limit"):
        fetch_server_app_installation(
            config=github_app_control_plane_config(),
            installation_id="12345",
            opener=opener,
            jwt_factory=lambda **kwargs: "server-app-jwt",
        )


def test_authenticated_app_identity_response_is_size_bounded():
    oversized = b"{" + b"x" * GITHUB_APP_VERIFICATION_RESPONSE_LIMIT_BYTES

    def opener(request, timeout):
        del timeout
        return FakeGitHubResponse(oversized, request.full_url)

    with pytest.raises(GitHubAppIdentityVerificationError, match="size limit"):
        fetch_authenticated_app_identity(
            github_app_control_plane_config(),
            opener=opener,
            jwt_factory=lambda **kwargs: "server-app-jwt",
        )


def test_user_authorization_response_is_size_bounded_before_server_proof():
    oversized = b"{" + b"x" * GITHUB_APP_VERIFICATION_RESPONSE_LIMIT_BYTES
    server_proof_attempted = False

    def opener(request, timeout):
        del timeout
        return FakeGitHubResponse(oversized, request.full_url)

    def fetcher(**kwargs):
        nonlocal server_proof_attempted
        del kwargs
        server_proof_attempted = True
        raise AssertionError("server proof must not run after an oversized response")

    with pytest.raises(GitHubUserVerificationError, match="size limit"):
        verify_project_github_binding(
            installation_id="12345",
            repository_id="4567",
            expected_github_repo="example-org/buzz",
            expected_api_url="https://api.github.com",
            github_user_access_token="yoke-app-user-token",
            opener=opener,
            control_plane_config=github_app_control_plane_config(),
            server_installation_fetcher=fetcher,
        )

    assert server_proof_attempted is False


def test_user_installation_collection_allows_a_valid_page_over_64_kib():
    events = []
    server = ServerVerifiedInstallation(
        installation_id="12345",
        account_id="9988",
        account_login="Example-Org",
        account_type="Organization",
        repository_selection="selected",
        permissions={"issues": "write", "checks": "read"},
        status="active",
    )

    def opener(request, timeout):
        del timeout
        path = urllib.parse.urlsplit(request.full_url).path
        events.append(path)
        if path == "/user":
            body = {"id": 77, "login": "octocat"}
        elif path == "/user/installations":
            installation = github_app_installation_payload()
            installation["large_valid_page_field"] = "x" * (
                GITHUB_APP_VERIFICATION_RESPONSE_LIMIT_BYTES + 1
            )
            body = {"installations": [installation]}
        else:
            body = {
                "repositories": [
                    {
                        "id": 4567,
                        "full_name": "Example-Org/Buzz",
                        "default_branch": "trunk",
                        "owner": {"id": 9988},
                    }
                ]
            }
        return FakeGitHubResponse(body, request.full_url)

    verified = verify_project_github_binding(
        installation_id="12345",
        repository_id="4567",
        expected_github_repo="example-org/buzz",
        expected_api_url="https://api.github.com",
        github_user_access_token="yoke-app-user-token",
        opener=opener,
        control_plane_config=github_app_control_plane_config(),
        server_installation_fetcher=lambda **kwargs: server,
    )

    assert verified.github_repo == "Example-Org/Buzz"
    assert events == [
        "/user",
        "/user/installations",
        "/user/installations/12345/repositories",
    ]


def test_user_installation_collection_rejects_beyond_collection_limit():
    oversized = b"{" + b"x" * GITHUB_APP_COLLECTION_RESPONSE_LIMIT_BYTES

    def opener(request, timeout):
        del timeout
        path = urllib.parse.urlsplit(request.full_url).path
        if path == "/user":
            return FakeGitHubResponse({"id": 77, "login": "octocat"}, request.full_url)
        return FakeGitHubResponse(oversized, request.full_url)

    with pytest.raises(GitHubUserVerificationError, match="size limit"):
        verify_project_github_binding(
            installation_id="12345",
            repository_id="4567",
            expected_github_repo="example-org/buzz",
            expected_api_url="https://api.github.com",
            github_user_access_token="yoke-app-user-token",
            opener=opener,
            control_plane_config=github_app_control_plane_config(),
        )


def test_verification_timeouts_are_typed_and_sanitized():
    def timeout(request, timeout):
        del request, timeout
        raise TimeoutError("provider detail must not escape")

    with pytest.raises(
        GitHubAppIdentityVerificationError, match="was unavailable"
    ) as identity_error:
        fetch_authenticated_app_identity(
            github_app_control_plane_config(),
            opener=timeout,
            jwt_factory=lambda **kwargs: "server-app-jwt",
        )
    assert "provider detail" not in str(identity_error.value)

    with pytest.raises(
        GitHubServerInstallationVerificationError, match="was unavailable"
    ) as installation_error:
        fetch_server_app_installation(
            config=github_app_control_plane_config(),
            installation_id="12345",
            opener=timeout,
            jwt_factory=lambda **kwargs: "server-app-jwt",
        )
    assert "provider detail" not in str(installation_error.value)

    with pytest.raises(GitHubUserVerificationError, match="timed out") as user_error:
        verify_project_github_binding(
            installation_id="12345",
            repository_id="4567",
            expected_github_repo="example-org/buzz",
            expected_api_url="https://api.github.com",
            github_user_access_token="yoke-app-user-token",
            opener=timeout,
            control_plane_config=github_app_control_plane_config(),
        )
    assert "provider detail" not in str(user_error.value)
