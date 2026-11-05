# ruff: noqa: F401, E402
"""Shared setup for tests in this directory."""

from __future__ import annotations

import json

from pathlib import Path

from types import SimpleNamespace

from typing import Any

import urllib.error

import pytest

from runtime.api.cli.github_app_machine_connection_test_support import (
    _api_opener,
)

from runtime.api.cli.github_app_machine_security_test_support import (
    _configured_machine,
    _profile_opener,
    _refresh_opener,
)

from yoke_cli.commands import merge_item_local_runtime as local_runtime

from yoke_cli.commands.adapters import github as github_adapter

from yoke_cli.config import github_local_user_access

from yoke_cli.config import github_machine

from yoke_cli.config import github_merge_path_binding as merge_path_binding

from yoke_core.domain.github_app_dispatch_context import LOCAL_USER_TOKEN_PROVIDER

SERVICE_API_URL = "https://api.upyoke.com"

ADMIN_ENV = "prod-db-admin"


def _connected_machine(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A valid stored grant on a machine whose active connection is HTTPS."""

    config, _credential = _configured_machine(tmp_path, monkeypatch)
    monkeypatch.delenv("YOKE_ENV", raising=False)
    payload = json.loads(config.read_text(encoding="utf-8"))
    token_file = config.parent / "service-token"
    token_file.write_text("service-token\n", encoding="utf-8")
    payload["active_env"] = "prod"
    payload["connections"] = {
        "prod": {
            "transport": "https",
            "api_url": SERVICE_API_URL,
            "credential_source": {"kind": "token_file", "path": str(token_file)},
        },
    }
    config.write_text(json.dumps(payload), encoding="utf-8")
    config.chmod(0o600)
    return config


def _admin_sibling_machine(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A connected machine whose https plane has an owner-only admin sibling."""

    config = _connected_machine(tmp_path, monkeypatch)
    payload = json.loads(config.read_text(encoding="utf-8"))
    payload["connections"][ADMIN_ENV] = {
        "transport": "local-postgres",
        "protected": True,
        "credential_source": {
            "kind": "dsn_file",
            "path": str(config.parent / "prod.dsn"),
        },
    }
    config.write_text(json.dumps(payload), encoding="utf-8")
    config.chmod(0o600)
    return config
