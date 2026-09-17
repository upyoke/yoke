"""Shared Git and GitHub App fixtures for credential-helper integration tests."""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess

from yoke_cli.config import github_git_credential_store


def run_git(root: Path, *args: str, input_text: str | None = None) -> str:
    env = dict(os.environ)
    env["GIT_CONFIG_GLOBAL"] = os.devnull
    env["GIT_CONFIG_NOSYSTEM"] = "1"
    result = subprocess.run(
        ["git", *args],
        cwd=root,
        input=input_text,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=True,
        env=env,
    )
    return result.stdout


def write_github_app_config(config: Path, credential: Path, token: str) -> None:
    github_git_credential_store.write_credential_document(
        credential,
        {
            "schema_version": 2,
            "refresh_token": "refresh-secret",
            "refresh_expires_at": "2099-12-09T17:00:00+00:00",
        },
    )
    config.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "active_env": "local",
                "connections": {
                    "local": {"transport": "local-postgres", "prod": False}
                },
                "github": {
                    "api_url": "https://api.github.com",
                    "web_url": "https://github.com",
                    "app_slug": "yoke",
                    "app_id": 123,
                    "client_id": "Iv1.local",
                    "profile_source": "local_explicit",
                    "authorization": {
                        "kind": "github_app_user_authorization",
                        "status": "authorized",
                        "refresh_credential_ref": str(credential),
                    },
                },
            }
        ),
        encoding="utf-8",
    )
    config.chmod(0o600)


__all__ = ["run_git", "write_github_app_config"]
