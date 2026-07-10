from __future__ import annotations

import pytest

from yoke_contracts import github_origin


def test_install_urls_follow_cloud_and_ghes_routes() -> None:
    cloud = github_origin.validate_github_endpoint_pair(
        "https://api.github.com", "https://github.com",
    )
    residency = github_origin.validate_github_endpoint_pair(
        "https://api.acme.ghe.com", "https://acme.ghe.com",
    )
    ghes = github_origin.validate_github_endpoint_pair(
        "https://github.example.com/api/v3", "https://github.example.com",
    )

    assert cloud.app_install_url("yoke") == (
        "https://github.com/apps/yoke/installations/new"
    )
    assert residency.app_install_url("yoke") == (
        "https://acme.ghe.com/apps/yoke/installations/new"
    )
    assert ghes.app_install_url("yoke") == (
        "https://github.example.com/github-apps/yoke/installations/new"
    )
    assert ghes.api.base_url == "https://github.example.com/api/v3"


@pytest.mark.parametrize(
    ("api_url", "web_url"),
    [
        ("https://api.github.com/wrong", "https://github.com"),
        ("https://api.github.com/%2f", "https://github.com"),
        ("https://github.example.com", "https://github.example.com"),
        ("https://github.example.com/api%2fv3", "https://github.example.com"),
        ("https://github.example.com/api/v4", "https://github.example.com"),
        ("https://github.example.com/api/v3", "https://github.example.com/base"),
    ],
)
def test_endpoint_pair_rejects_noncanonical_paths(
    api_url: str, web_url: str,
) -> None:
    with pytest.raises(
        github_origin.GitHubApiOriginError,
        match="canonical bases",
    ):
        github_origin.validate_github_endpoint_pair(api_url, web_url)


@pytest.mark.parametrize("installation_id", [True, 0, -1, "123"])
def test_installation_settings_url_rejects_noninteger_ids(
    installation_id: object,
) -> None:
    endpoint_pair = github_origin.validate_github_endpoint_pair(
        "https://api.github.com", "https://github.com",
    )

    with pytest.raises(
        github_origin.GitHubApiOriginError,
        match="positive integer",
    ):
        endpoint_pair.installation_settings_url(installation_id)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "url",
    [
        "https://github.example.com/login/oauth",
        "https://github.example.com/api/v30/user",
        "https://github.example.com/api/v3/../settings",
        "https://github.example.com/api/v3/%2e%2e/settings",
        "https://github.example.com/api/v3%2f%2e%2e/settings",
        "https://github.example.com/api/v3/user\nX-Evil: yes",
    ],
)
def test_ghes_api_request_cannot_leave_configured_base_path(url: str) -> None:
    endpoint = github_origin.validate_github_api_endpoint(
        "https://github.example.com/api/v3"
    )

    with pytest.raises(github_origin.GitHubApiOriginError):
        github_origin.require_same_github_origin(url, endpoint)


def test_ghes_api_request_accepts_base_path_and_query() -> None:
    endpoint = github_origin.validate_github_api_endpoint(
        "https://github.example.com/api/v3"
    )

    github_origin.require_same_github_origin(
        "https://github.example.com/api/v3/user?per_page=100", endpoint,
    )
    github_origin.require_same_github_origin(
        "https://github.example.com/api/graphql", endpoint,
    )


@pytest.mark.parametrize(
    "value",
    [
        "https://api.github.com\nEVIL=x",
        "https://api.github.com\t.evil.example",
        "https://bad host.example",
        "https://bad=host.example",
        "https://-bad.example",
        "https://bad_.example",
        "https://999.999.999.999",
        "https://[gggg::1]",
        "https://api.github.com/%0a",
    ],
)
def test_endpoint_rejects_invalid_hosts_and_encoded_controls(value: str) -> None:
    with pytest.raises(github_origin.GitHubApiOriginError):
        github_origin.validate_github_api_endpoint(value)


def test_repository_ssh_url_rejects_nonstandard_port() -> None:
    with pytest.raises(
        github_origin.GitHubApiOriginError,
        match="port 22",
    ):
        github_origin.normalize_github_repository(
            "ssh://git@github.example:2222/owner/repo.git",
            web_url="https://github.example",
        )
