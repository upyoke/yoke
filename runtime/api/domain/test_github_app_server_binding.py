"""Server-App ownership proof for project GitHub repository binding."""

from __future__ import annotations

import urllib.error

import pytest

from runtime.api.domain.github_app_server_verification_test_support import (
    FakeGitHubResponse,
    github_app_control_plane_config,
    github_app_installation_payload,
    github_user_opener,
)
from yoke_core.domain.github_api_transport import _RejectRedirectHandler
from yoke_core.domain.github_app_server_installation import (
    GitHubServerInstallationVerificationError,
    ServerVerifiedInstallation,
    fetch_server_app_installation,
)
from yoke_core.domain.github_app_user_verification import (
    GitHubUserVerificationError,
    verify_project_github_binding,
)


def test_server_app_jwt_fetches_canonical_installation_without_redirect():
    seen = []

    def opener(request, timeout):
        seen.append((request, timeout))
        return FakeGitHubResponse(github_app_installation_payload(), request.full_url)

    verified = fetch_server_app_installation(
        config=github_app_control_plane_config(),
        installation_id="12345",
        opener=opener,
        jwt_factory=lambda **kwargs: "server-app-jwt",
        timeout_seconds=4.0,
    )

    assert verified.installation_id == "12345"
    assert verified.account_login == "Example-Org"
    request, timeout = seen[0]
    assert request.full_url == "https://api.github.com/app/installations/12345"
    assert request.get_header("Authorization") == "Bearer server-app-jwt"
    assert timeout == 4.0


def test_foreign_app_installation_is_rejected_before_repository_lookup():
    user_events = []

    def denied(request, timeout):
        del timeout
        raise urllib.error.HTTPError(
            request.full_url,
            404,
            "Not Found",
            None,
            None,
        )

    def fetch_foreign(**kwargs):
        return fetch_server_app_installation(
            **kwargs,
            jwt_factory=lambda **values: "server-app-jwt",
        )

    with pytest.raises(
        GitHubUserVerificationError,
        match="configured GitHub App cannot access",
    ):
        verify_project_github_binding(
            installation_id="12345",
            repository_id="4567",
            expected_github_repo="example-org/buzz",
            expected_api_url="https://api.github.com",
            github_user_access_token="foreign-app-user-token",
            opener=github_user_opener(user_events),
            control_plane_config=github_app_control_plane_config(),
            server_installation_opener=denied,
            server_installation_fetcher=fetch_foreign,
        )

    assert user_events == ["/user", "/user/installations"]


def test_matching_server_app_is_proven_before_repository_binding():
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

    def fetcher(**kwargs):
        events.append("server-proof")
        return server

    verified = verify_project_github_binding(
        installation_id="12345",
        repository_id="4567",
        expected_github_repo="example-org/buzz",
        expected_api_url="https://api.github.com",
        github_user_access_token="yoke-app-user-token",
        opener=github_user_opener(events),
        control_plane_config=github_app_control_plane_config(),
        server_installation_fetcher=fetcher,
    )

    assert verified.github_repo == "Example-Org/Buzz"
    assert events == [
        "/user",
        "/user/installations",
        "server-proof",
        "/user/installations/12345/repositories",
    ]


def test_server_installation_redirect_cannot_cross_origin():
    def redirect(request, timeout):
        del request, timeout
        return FakeGitHubResponse(
            github_app_installation_payload(),
            "https://attacker.example/collect",
        )

    with pytest.raises(
        GitHubServerInstallationVerificationError,
        match="crossed",
    ):
        fetch_server_app_installation(
            config=github_app_control_plane_config(),
            installation_id="12345",
            opener=redirect,
            jwt_factory=lambda **kwargs: "server-app-jwt",
        )


def test_server_installation_redirect_cannot_change_same_origin_path():
    def redirect(request, timeout):
        del request, timeout
        return FakeGitHubResponse(
            github_app_installation_payload(),
            "https://api.github.com/app/installations/54321",
        )

    with pytest.raises(
        GitHubServerInstallationVerificationError,
        match="must not redirect",
    ):
        fetch_server_app_installation(
            config=github_app_control_plane_config(),
            installation_id="12345",
            opener=redirect,
            jwt_factory=lambda **kwargs: "server-app-jwt",
        )


def test_verification_redirect_handler_never_follows():
    handler = _RejectRedirectHandler()

    assert (
        handler.redirect_request(
            None,
            None,
            302,
            "Found",
            {},
            "https://api.github.com/another-path",
        )
        is None
    )
