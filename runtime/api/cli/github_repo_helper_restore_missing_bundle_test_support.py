# ruff: noqa: F401, E402
"""Shared setup for tests in this directory."""

from __future__ import annotations

import json

from pathlib import Path

import shutil

import pytest

from runtime.api.cli.github_git_credential_install_test_support import (
    _configured_repo,
    _git,
)

from runtime.api.cli.github_repo_helper_reconnect_test_support import (
    _register_checkout,
)

from yoke_cli.config import github_git_credentials

from yoke_cli.config import github_repo_config

from yoke_cli.config import github_repo_helper_reconnect


def _register_checkouts(config: Path, repos: list[Path], tmp_path: Path) -> None:
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
                "stage": [
                    {"checkout": str(repo), "project_id": project_id}
                    for project_id, repo in enumerate(repos, start=1)
                ]
            },
        }
    )
    config.write_text(json.dumps(payload), encoding="utf-8")
