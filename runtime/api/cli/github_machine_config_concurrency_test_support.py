# ruff: noqa: F401, E402
"""Shared setup for tests in this directory."""

from __future__ import annotations

import json

from pathlib import Path

from typing import Any

import pytest

from yoke_cli.config import github_machine, github_machine_state

from yoke_cli.config import github_user_tokens, machine_config, writer
from yoke_contracts.machine_config import secret_files as secrets

from yoke_contracts import github_app_installation_permissions

from yoke_contracts.machine_config import schema as contract


def _token_response(label: str) -> dict[str, Any]:
    return {
        "access_token": f"access-{label}",
        "expires_in": 28800,
        "refresh_token": f"refresh-{label}",
        "refresh_token_expires_in": 15552000,
        "scope": "",
    }


def _seed_connection(
    config: Path,
    label: str,
    *,
    service_api_url: str | None = None,
) -> tuple[dict[str, Any], Path]:
    credential_id = label.encode("utf-8").hex().ljust(32, "0")[:32]
    credential = secrets.secret_path(f"github-app-user-{credential_id}", "json")
    github_user_tokens.store_initial_token(
        credential,
        _token_response(label),
        device_flow_completed=True,
        config_path=config,
    )
    github = {
        "api_url": contract.DEFAULT_GITHUB_API_URL,
        "web_url": contract.DEFAULT_GITHUB_WEB_URL,
        "app_slug": "yoke-local",
        "app_id": 123,
        "client_id": "Iv1.local",
        "profile_source": (
            contract.GITHUB_PROFILE_SOURCE_SERVICE
            if service_api_url
            else contract.GITHUB_PROFILE_SOURCE_LOCAL_EXPLICIT
        ),
        "authorization": {
            "kind": contract.GITHUB_AUTH_KIND_USER_AUTHORIZATION,
            "refresh_credential_ref": str(credential),
            "status": "authorized",
        },
    }
    if service_api_url:
        github["profile_service_api_url"] = service_api_url
    return github, credential
