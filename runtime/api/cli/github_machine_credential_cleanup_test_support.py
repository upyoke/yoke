# ruff: noqa: F401, E402
"""Shared setup for tests in this directory."""

from __future__ import annotations

import json

from pathlib import Path

import shlex

import sys

import pytest

from yoke_cli.config import github_git_credential_launcher

from yoke_cli.config import github_git_credential_store

from yoke_cli.config import github_git_credentials

from yoke_cli.config import github_machine_state

from yoke_cli.config import github_user_tokens

from yoke_cli.config import writer

from yoke_cli.config import writer_github

from yoke_contracts.machine_config import schema as contract


def _config(path: Path, credential_ref: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
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
                        "refresh_credential_ref": str(credential_ref),
                        "status": "authorized",
                    },
                },
            }
        ),
        encoding="utf-8",
    )


def _base_config(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "active_env": "local",
                "connections": {
                    "local": {
                        "transport": "local-postgres",
                        "protected": False,
                        "credential_source": {
                            "kind": "dsn_file",
                            "path": str(path.parent / "local.dsn"),
                        },
                    },
                },
            }
        ),
        encoding="utf-8",
    )


def _github_entry(credential_ref: Path) -> dict:
    return {
        "api_url": contract.DEFAULT_GITHUB_API_URL,
        "web_url": contract.DEFAULT_GITHUB_WEB_URL,
        "app_slug": "yoke",
        "app_id": 123,
        "client_id": "Iv1.local",
        "profile_source": contract.GITHUB_PROFILE_SOURCE_LOCAL_EXPLICIT,
        "authorization": {
            "kind": contract.GITHUB_AUTH_KIND_USER_AUTHORIZATION,
            "refresh_credential_ref": str(credential_ref),
            "status": "authorized",
        },
    }
