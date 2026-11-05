# ruff: noqa: F401, E402
"""Shared setup for tests in this directory."""

import json

import pytest

from pathlib import Path

from yoke_cli.config import machine_config, writer_projects

from yoke_contracts.machine_config import schema_projects

from runtime.api.cli.project_uninstall_owned_cleanup_test_support import (
    installed as installed,
)


def seed_project(root, config=None, project_id=7):
    config = Path(config) if config else machine_config.config_path()
    config.parent.mkdir(parents=True, exist_ok=True)
    payload = json.loads(config.read_text()) if config.exists() else {}
    token = config.parent / "test.token"
    token.write_text("fixture-token\n")
    if payload.get("github"):
        payload["github"]["profile_source"] = "local_explicit"
    payload.update(
        {
            "schema_version": 1,
            "active_env": "test",
            "connections": {
                "test": {
                    "transport": "https",
                    "api_url": "https://test.invalid",
                    "credential_source": {"kind": "token_file", "path": str(token)},
                },
            },
        }
    )
    config.write_text(json.dumps(payload))
    writer_projects.register_project(root, project_id, path=config)
    return config
