# ruff: noqa: F401, E402
"""Shared setup for tests in this directory."""

import io

import json

import subprocess

from pathlib import Path

from tests.installer.public_installer_helpers import (
    RecordingRunner,
    branded_installer_glyphs as branded_installer_glyphs,
    load_installer,
    write_channel,
)


def _options(installer_mod, **overrides):
    base = dict(
        channel="stable",
        version=None,
        yes=False,
        dry_run=False,
        base_url="https://api.upyoke.com",
        no_setup=False,
    )
    base.update(overrides)
    return installer_mod.InstallOptions(**base)


def _status_ok(version: str = "0.1.0"):
    payload = json.dumps(
        {
            "ok": True,
            "runtime": {
                "package_versions": {
                    "yoke-cli": version,
                    "yoke-contracts": version,
                    "yoke-harness": version,
                    "yoke-core": version,
                },
            },
            "connection": {"client_authority": "api", "transport": "https"},
        }
    )
    return subprocess.CompletedProcess(["yoke", "status", "--json"], 0, payload, "")


def _installed_yoke_path(tmp_path: Path, monkeypatch) -> str:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    yoke_bin = bin_dir / "yoke"
    yoke_bin.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    yoke_bin.chmod(0o755)
    monkeypatch.setenv("XDG_BIN_HOME", str(bin_dir))
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    return str(yoke_bin)
