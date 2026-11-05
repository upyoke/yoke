# ruff: noqa: F401, E402
"""Shared setup for tests in this directory."""

import json

from pathlib import Path

import pytest

from yoke_cli.commands.adapters import onboard as onboard_adapter

from yoke_cli.config import onboard_apply_connection

from yoke_cli.config import onboard_apply_report

from yoke_cli.config import onboard_wizard


def _preview() -> dict:
    return {
        "operation": "onboard",
        "mode": "quick",
        "project_mode": "machine-only",
        "config_path": "/tmp/home/config.json",
        "plan": {
            "project": None,
            "steps": [
                {"action": "create-or-validate-dir", "target": "/tmp/home"},
                {"action": "set-active-env", "target": "stage"},
                {"action": "store-token-reference", "target": "/tmp/token"},
            ],
        },
    }
