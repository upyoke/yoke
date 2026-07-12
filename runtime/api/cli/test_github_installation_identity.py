"""GitHub installation identity and repair-link trust boundaries."""

from __future__ import annotations

import pytest

from runtime.api.cli.test_github_app_machine_connection import (
    _Response,
    _api_opener,
)
from yoke_cli.config import github_app_user_api, github_machine_access


def _discovery_with_html_url(html_url: str) -> dict:
    def opener(request, timeout):
        if request.full_url.endswith("/user"):
            return _Response(
                {"id": 42, "login": "octocat"}, url=request.full_url,
            )
        if "/user/installations?" in request.full_url:
            return _Response({"installations": [{
                "id": 123, "app_id": 123, "app_slug": "yoke-local",
                "html_url": html_url,
                "account": {
                    "id": 9, "login": "octo-org", "type": "Organization",
                },
                "repository_selection": "selected", "permissions": {},
            }]}, url=request.full_url)
        if "/repositories?" in request.full_url:
            return _Response({"repositories": []}, url=request.full_url)
        raise AssertionError(request.full_url)

    return github_app_user_api.discover_access(
        api_url="https://api.github.com", web_url="https://github.com",
        access_token="access", opener=opener,
    )


@pytest.mark.parametrize("html_url", [
    "https://github.com/settings/installations/123",
    "https://github.com/organizations/octo-org/settings/installations/123",
])
def test_discovery_preserves_safe_installation_settings_url(
    html_url: str,
) -> None:
    snapshot = _discovery_with_html_url(html_url)
    assert snapshot["installations"][0]["html_url"] == html_url


@pytest.mark.parametrize("html_url", [
    "https://attacker.example/settings/installations/123",
    "https://github.com/settings/installations/999",
])
def test_discovery_omits_unsafe_installation_settings_url(
    html_url: str,
) -> None:
    snapshot = _discovery_with_html_url(html_url)
    assert "html_url" not in snapshot["installations"][0]


@pytest.mark.parametrize("expected_app_id,expected_app_slug", [
    (999, "yoke-local"),
    (123, "Yoke-Local"),
])
def test_access_discovery_rejects_different_app_installations(
    expected_app_id: int,
    expected_app_slug: str,
) -> None:
    with pytest.raises(
        github_app_user_api.GitHubAppUserApiError,
        match="different App profile",
    ):
        github_machine_access.discover_access_with_unauthorized_retry(
            api_url="https://api.github.com", web_url="https://github.com",
            access_token="access", opener=_api_opener(installed=True),
            sleep=lambda seconds: None,
            expected_app_id=expected_app_id,
            expected_app_slug=expected_app_slug,
        )
