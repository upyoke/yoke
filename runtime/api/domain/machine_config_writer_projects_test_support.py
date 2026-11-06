# ruff: noqa: F401, E402
"""Shared setup for tests in this directory."""

from __future__ import annotations

import json

from pathlib import Path

import pytest

from yoke_core.domain import machine_config_writer as writer

from yoke_core.domain.machine_config_writer import MachineConfigWriteError


@pytest.fixture()
def home(tmp_path, monkeypatch):
    machine_home = tmp_path / "machine-home"
    monkeypatch.setenv("YOKE_MACHINE_HOME", str(machine_home))
    monkeypatch.delenv("YOKE_MACHINE_CONFIG_FILE", raising=False)
    monkeypatch.delenv("YOKE_ENV", raising=False)
    return machine_home


def _config(home: Path) -> dict:
    return json.loads((home / "config.json").read_text())


def _seed_https(home: Path, tmp_path: Path, env: str = "stage") -> Path:
    token_file = tmp_path / f"{env}.token"
    token_file.write_text("tok\n")
    writer.set_connection(
        env,
        transport="https",
        api_url="https://api.example",
        token_file=str(token_file),
    )
    return token_file
