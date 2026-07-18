"""Shared fake transport state for server-backed GitHub App verification."""

from __future__ import annotations

import json
import urllib.parse

from yoke_contracts.github_origin import validate_github_api_endpoint
from yoke_core.domain.github_app_control_plane import GitHubAppControlPlaneConfig


class FakeGitHubResponse:
    def __init__(self, body, url: str) -> None:
        self._body = (
            body if isinstance(body, bytes) else json.dumps(body).encode("utf-8")
        )
        self._url = url

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        return False

    def geturl(self) -> str:
        return self._url

    def read(self, size: int = -1) -> bytes:
        return self._body if size < 0 else self._body[:size]


def github_app_control_plane_config() -> GitHubAppControlPlaneConfig:
    return GitHubAppControlPlaneConfig(
        issuer="123456",
        private_key_pem="test-private-key",
        endpoint=validate_github_api_endpoint("https://api.github.com"),
        private_key_file="/run/secrets/test-key",
    )


def github_app_installation_payload() -> dict[str, object]:
    return {
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


def github_user_opener(events):
    def open_request(request, timeout):
        del timeout
        path = urllib.parse.urlsplit(request.full_url).path
        events.append(path)
        if path == "/user":
            body = {"id": 77, "login": "octocat"}
        elif path == "/user/installations":
            body = {"installations": [github_app_installation_payload()]}
        else:
            assert path == "/user/installations/12345/repositories"
            body = {
                "repositories": [
                    {
                        "id": 4567,
                        "full_name": "Example-Org/ExternalWebapp",
                        "default_branch": "trunk",
                        "owner": {"id": 9988},
                    }
                ]
            }
        return FakeGitHubResponse(body, request.full_url)

    return open_request


__all__ = [
    "FakeGitHubResponse",
    "github_app_control_plane_config",
    "github_app_installation_payload",
    "github_user_opener",
]
