# ruff: noqa: F401, E402
"""Shared setup for tests in this directory."""

import copy

import json

from pathlib import Path

import pytest

from runtime.api.cli.github_machine_config_concurrency_test_support import (
    _seed_connection,
)

from yoke_cli.config import github_git_credential_helper as helper

from yoke_cli.config import github_git_credential_store as store

from yoke_cli.config import github_machine_profile, machine_config, writer

from yoke_contracts import cursor_permissions, github_app_tokens

from yoke_contracts.machine_config import schema as contract


@pytest.fixture
def configured(tmp_path, monkeypatch):
    monkeypatch.setenv("YOKE_MACHINE_HOME", str(tmp_path))
    monkeypatch.delenv("YOKE_ENV", raising=False)
    config = tmp_path / "config.json"
    payload = {
        "schema_version": 1,
        "active_env": "prod",
        "connections": {
            label: {
                "transport": "https",
                "api_url": f"https://{label}.example.test",
                "protected": False,
                "credential_source": {
                    "kind": "token_file",
                    "path": str(tmp_path / label),
                },
            }
            for label in ("prod", "stage")
        },
    }
    for label in ("prod-db-admin", "local"):
        payload["connections"][label] = {
            "transport": "local-postgres",
            "protected": False,
            "credential_source": {"kind": "dsn_file", "path": str(tmp_path / label)},
        }
    config.write_text(json.dumps(payload))
    a, a_path = _seed_connection(
        config, "prod", service_api_url="https://prod.example.test"
    )
    b, b_path = _seed_connection(
        config, "stage", service_api_url="https://stage.example.test"
    )
    return config, payload, a, b, a_path, b_path


def save(config, payload):
    config.write_text(json.dumps(payload))
    config.chmod(0o600)
