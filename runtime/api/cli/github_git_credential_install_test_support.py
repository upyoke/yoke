# ruff: noqa: F401, E402
"""Shared setup for tests in this directory."""

from __future__ import annotations

import json

from pathlib import Path

import subprocess

import pytest

from yoke_cli.config import github_git_credential_store

from yoke_cli.config import github_git_credentials

from yoke_cli.config import github_machine

from yoke_cli.config import machine_config

from yoke_contracts.machine_config import schema as contract


def _git(
    root: Path, *args: str, check: bool = True
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=root,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=check,
    )


def _configured_repo(tmp_path: Path, monkeypatch) -> tuple[Path, Path, Path]:
    home = tmp_path / "home"
    monkeypatch.setenv("YOKE_MACHINE_HOME", str(home))
    credential = home / "secrets" / f"github-app-user-{'a' * 32}.json"
    github_git_credential_store.write_credential_document(
        credential,
        {
            "schema_version": 2,
            "refresh_token": "refresh-secret",
            "refresh_expires_at": "2099-12-09T17:00:00+00:00",
        },
    )
    config = home / "config.json"
    config.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "github": {
                    "api_url": contract.DEFAULT_GITHUB_API_URL,
                    "web_url": contract.DEFAULT_GITHUB_WEB_URL,
                    "app_slug": "yoke",
                    "app_id": 123,
                    "client_id": "Iv1.local",
                    "authorization": {
                        "kind": contract.GITHUB_AUTH_KIND_USER_AUTHORIZATION,
                        "refresh_credential_ref": str(credential),
                        "status": "authorized",
                    },
                },
            }
        ),
        encoding="utf-8",
    )
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "--initial-branch", "main")
    return repo, config, credential
