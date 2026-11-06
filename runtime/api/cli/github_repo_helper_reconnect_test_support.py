# ruff: noqa: F401, E402
"""Shared setup for tests in this directory."""

from __future__ import annotations

from runtime.api.cli.github_user_token_test_support import seed_yoke_connection

import json

from pathlib import Path

import urllib.error

import pytest

from runtime.api.cli.github_app_machine_connection_test_support import (
    _alternate_profile_opener,
    _api_opener,
    _device_opener,
    _explicit_profile,
    _profile_opener,
)

from runtime.api.cli.github_git_credential_install_test_support import (
    _configured_repo,
    _git,
)

from yoke_cli.config import github_git_credentials, github_machine


def _register_checkout(config: Path, repo: Path, tmp_path: Path) -> None:
    payload = json.loads(config.read_text(encoding="utf-8"))
    payload.update(
        {
            "active_env": "stage",
            "connections": {
                "stage": {
                    "transport": "https",
                    "api_url": "https://stage.yoke.example",
                    "credential_source": {
                        "kind": "token_file",
                        "path": str(tmp_path / "actor.token"),
                    },
                }
            },
            "connection_projects": {
                "stage": [{"checkout": str(repo), "project_id": 1}]
            },
        }
    )
    slots = payload.get("connection_github", {})
    if "local" in slots:
        slots["stage"] = slots.pop("local")
        slots["stage"].update(
            profile_source="service",
            profile_service_api_url="https://stage.yoke.example",
        )
    config.write_text(json.dumps(payload), encoding="utf-8")
    _git(repo, "remote", "add", "origin", "https://github.com/octo/repo.git")
