# ruff: noqa: F401, E402
"""Shared setup for tests in this directory."""

from __future__ import annotations

from runtime.api.cli.yoke_operations_cli_onboard_apply_report_test_support import _preview as _preview

import json

from pathlib import Path

from types import SimpleNamespace

import pytest

from yoke_cli.commands.adapters import onboard as onboard_adapter

from yoke_cli.commands.adapters import onboard_build_report

from yoke_cli.config import onboard_apply_report

from yoke_cli.config import onboard_apply_resume

from yoke_cli.config import onboard_checkout_ownership

from yoke_cli.config import onboard_project

from yoke_cli.config.project_clone_support import ClonePlan

from yoke_cli.config.project_publish_support import PublishRequest
