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

from yoke_contracts.machine_config.relay_instance import (
    RelayInstanceError,
    resolve_relay_instance,
)

from yoke_core.domain.relay_launchd_status import RELAY_KEEP_ALIVE
from yoke_core.domain.relay_launchd_status import RELAY_LAUNCHD_LABEL
from yoke_core.domain.relay_launchd_status import relay_launchd_paths
from yoke_core.domain.relay_launchd_status import relay_launchd_status
from yoke_core.domain.relay_launchd_status import relay_plist_document
from yoke_core.tools.session_relay_plist import install_relay_launchd, uninstall_relay_launchd

from yoke_core.domain.relay_release_path import relay_launch_executable


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
