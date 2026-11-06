# ruff: noqa: F401, E402
"""Shared setup for tests in this directory."""

from __future__ import annotations

import json

import os

from pathlib import Path

import plistlib

import subprocess

import pytest

from yoke_cli.config import machine_config

from yoke_cli.config.session_relay_instance import (
    RelayInstanceError,
    resolve_relay_instance,
)

from yoke_core.tools.session_relay_plist import (
    RELAY_KEEP_ALIVE,
    RELAY_LAUNCHD_LABEL,
    install_relay_launchd,
    relay_launchd_paths,
    relay_launchd_status,
    relay_plist_document,
    uninstall_relay_launchd,
)

from yoke_core.tools.session_relay_release import relay_launch_executable


def _config(tmp_path: Path) -> Path:
    path = tmp_path / ".yoke" / "config.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    connections = {}
    for environment, prod in (("prod", True), ("stage", False)):
        connections[environment] = {
            "transport": "https",
            "prod": prod,
            "api_url": f"https://{environment}.example.test",
            "credential_source": {
                "kind": "token_file",
                "path": f"~/.yoke/secrets/{environment}.token",
            },
        }
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "active_env": "prod",
                "connections": connections,
                "projects": [],
            }
        ),
        encoding="utf-8",
    )
    return path


def _pin_release(*, instance) -> None:
    executable = relay_launch_executable(instance.state_dir)
    executable.parent.mkdir(parents=True, exist_ok=True)
    executable.touch()
