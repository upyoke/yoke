# ruff: noqa: F401, E402
"""Shared setup for tests in this directory."""

from __future__ import annotations

from runtime.api.cli.github_app_machine_connection_test_support import _permissions as _permissions

from datetime import datetime, timezone

import json

from pathlib import Path

from typing import Any

import pytest

from yoke_cli.config import github_device_flow

from yoke_cli.config import github_app_user_api

from yoke_cli.config import github_git_credential_store

from yoke_cli.config import github_machine

from yoke_cli.config import github_machine_state

from yoke_cli.config import writer

from yoke_contracts import github_app_installation_permissions

from yoke_contracts.machine_config import schema as contract


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


def _configured_machine(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    auth_kind: str = contract.GITHUB_AUTH_KIND_USER_AUTHORIZATION,
    credential_ref: Path | None = None,
) -> tuple[Path, Path]:
    home = tmp_path / "home"
    monkeypatch.setenv("YOKE_MACHINE_HOME", str(home))
    config = home / "config.json"
    credential = credential_ref or home / "secrets" / f"github-app-user-{'a' * 32}.json"
    if credential_ref is None:
        github_git_credential_store.write_credential_document(
            credential,
            {
                "schema_version": 2,
                "refresh_token": "refresh-secret",
                "refresh_expires_at": "2099-12-09T17:00:00+00:00",
                "config_owners": [str(config.resolve())],
                "config_ownership_complete": True,
            },
        )
    config.parent.mkdir(parents=True, exist_ok=True)
    config.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "active_env": "local",
                "connections": {
                    "local": {
                        "transport": "https",
                        "api_url": "https://api.upyoke.com",
                        "credential_source": {
                            "kind": "token_file",
                            "path": str(home / "token"),
                        },
                    }
                },
                "github": {
                    "api_url": contract.DEFAULT_GITHUB_API_URL,
                    "web_url": contract.DEFAULT_GITHUB_WEB_URL,
                    "app_slug": "yoke-local",
                    "app_id": 123,
                    "client_id": "Iv1.local",
                    "profile_source": contract.GITHUB_PROFILE_SOURCE_SERVICE,
                    "profile_service_api_url": "https://api.upyoke.com",
                    "authorization": {
                        "kind": auth_kind,
                        "refresh_credential_ref": str(credential),
                        "status": "authorized",
                        "github_user_id": 42,
                        "login": "octocat",
                    },
                    "installations": [
                        {
                            "installation_id": 123,
                            "app_id": 123,
                            "app_slug": "yoke-local",
                            "account_id": 9,
                            "account_login": "octo-org",
                            "account_type": "Organization",
                            "repository_selection": "selected",
                            "suspended": False,
                            "permissions": _permissions(),
                        }
                    ],
                    "repositories": [
                        {
                            "repository_id": 456,
                            "installation_id": 123,
                            "full_name": "octo-org/app",
                            "default_branch": "main",
                            "private": True,
                        }
                    ],
                },
            }
        ),
        encoding="utf-8",
    )
    return config, credential


def _empty_installation_opener(request, timeout):
    if request.full_url.endswith("/user"):
        return _Response(
            {"id": 42, "login": "octocat"},
            url=request.full_url,
        )
    if "/user/installations?" in request.full_url:
        return _Response({"installations": []}, url=request.full_url)
    raise AssertionError(request.full_url)


def _profile_opener(request, timeout):
    return _Response(
        {
            "github_app": {
                "available": True,
                "client_id": "Iv1.local",
                "app_slug": "yoke-local",
                "app_id": 123,
                "api_url": contract.DEFAULT_GITHUB_API_URL,
                "web_url": contract.DEFAULT_GITHUB_WEB_URL,
            }
        },
        url=request.full_url,
    )


def _refresh_opener(request, timeout):
    return _Response(
        {
            "access_token": "refreshed-access",
            "expires_in": 28_800,
            "refresh_token": "refreshed-refresh",
            "refresh_token_expires_in": 15_552_000,
        },
        url=request.full_url,
    )
