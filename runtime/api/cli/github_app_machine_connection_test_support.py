# ruff: noqa: F401, E402
"""Shared setup for tests in this directory."""

from __future__ import annotations

from runtime.api.cli.github_user_token_test_support import seed_yoke_connection

import json

from pathlib import Path

import stat

from typing import Any

from yoke_cli.config import github_app_user_api, github_machine

from yoke_contracts import github_app_installation_permissions


class _Response:
    def __init__(self, payload: dict[str, Any], *, url: str = "") -> None:
        self.payload = payload
        self.url = url

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        return False

    def read(self, size: int = -1) -> bytes:
        body = json.dumps(self.payload).encode("utf-8")
        return body[:size] if size >= 0 else body

    def geturl(self) -> str:
        return self.url


def _explicit_profile() -> dict[str, Any]:
    return {
        "client_id": "Iv1.local",
        "app_slug": "yoke-local",
        "app_id": 123,
        "api_url": "https://api.github.com",
        "web_url": "https://github.com",
    }


def _profile_opener(request, timeout):
    return _Response(
        {"github_app": {"available": True, **_explicit_profile()}},
        url=request.full_url,
    )


def _alternate_profile() -> dict[str, Any]:
    return {
        **_explicit_profile(),
        "client_id": "Iv1.other",
        "app_slug": "yoke-other",
        "app_id": 456,
    }


def _alternate_profile_opener(request, timeout):
    return _Response(
        {"github_app": {"available": True, **_alternate_profile()}},
        url=request.full_url,
    )


def _device_opener():
    responses = iter(
        [
            {
                "device_code": "device-secret",
                "user_code": "ABCD-EFGH",
                "verification_uri": "https://github.com/login/device",
                "expires_in": 900,
                "interval": 5,
            },
            {
                "access_token": "access-secret",
                "expires_in": 28800,
                "refresh_token": "refresh-secret",
                "refresh_token_expires_in": 15552000,
                "scope": "",
            },
        ]
    )
    return lambda request, timeout: _Response(
        next(responses),
        url=request.full_url,
    )


def _permissions() -> dict[str, str]:
    return {
        item.key: item.access
        for item in github_app_installation_permissions.REQUIRED_GITHUB_APP_REPOSITORY_PERMISSIONS
    }


def _api_opener(
    *,
    installed: bool,
    app_id: int = 123,
    app_slug: str = "yoke-local",
):
    def open_request(request, timeout):
        url = request.full_url
        if url.endswith("/user"):
            return _Response({"id": 42, "login": "octocat"}, url=url)
        if "/user/installations?" in url:
            if not installed:
                return _Response(
                    {"total_count": 0, "installations": []},
                    url=url,
                )
            return _Response(
                {
                    "total_count": 1,
                    "installations": [
                        {
                            "id": 123,
                            "app_id": app_id,
                            "app_slug": app_slug,
                            "html_url": (
                                "https://github.com/organizations/octo-org/"
                                "settings/installations/123"
                            ),
                            "account": {
                                "id": 9,
                                "login": "octo-org",
                                "type": "Organization",
                            },
                            "repository_selection": "selected",
                            "permissions": _permissions(),
                            "suspended_at": None,
                        }
                    ],
                },
                url=url,
            )
        if "/user/installations/123/repositories?" in url:
            return _Response(
                {
                    "total_count": 1,
                    "repositories": [
                        {
                            "id": 456,
                            "full_name": "octo-org/app",
                            "default_branch": "main",
                            "private": True,
                        }
                    ],
                },
                url=url,
            )
        raise AssertionError(f"unexpected GitHub API request: {url}")

    return open_request
