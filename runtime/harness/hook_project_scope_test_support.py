# ruff: noqa: F401, E402
"""Shared setup for tests in this directory."""

from __future__ import annotations

import subprocess

from pathlib import Path

import pytest

from yoke_contracts.hook_runner import project_scope

from yoke_core.hooks import codex_payload, target


@pytest.fixture
def project_map(tmp_path, monkeypatch):
    config_file = tmp_path / "config.json"
    config_file.write_text("{}")
    config = {"active_env": "local", "connection_projects": {"local": []}}
    monkeypatch.setattr(
        project_scope.machine_config, "config_path", lambda: config_file
    )
    monkeypatch.setattr(
        project_scope.machine_config, "load_config", lambda *_args, **_kwargs: config
    )
    return config
