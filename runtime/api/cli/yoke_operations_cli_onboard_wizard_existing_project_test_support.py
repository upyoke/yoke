# ruff: noqa: F401, E402
"""Shared setup for tests in this directory."""

from __future__ import annotations

from runtime.api.cli.onboard_wizard_github_navigation_safety_test_support import _body_text as _body_text

import asyncio

import json

from pathlib import Path

import subprocess

import pytest

pytest.importorskip("textual")

from textual.widgets import Static  # noqa: E402

from yoke_cli.config import existing_project_lookup  # noqa: E402

from yoke_cli.config.onboard_wizard import WizardDefaults  # noqa: E402

from runtime.api.cli.onboard_wizard_test_helpers import (  # noqa: E402
    advance_past_path,
    make_app,
    skip_hosting,
    stub_path_doctor,
    type_text,
)


def _configure_origin(checkout: Path, repo: str) -> None:
    subprocess.run(
        ["git", "init", "--initial-branch", "main"],
        cwd=checkout,
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    subprocess.run(
        [
            "git",
            "-c",
            "user.name=Yoke Test",
            "-c",
            "user.email=yoke-test@example.invalid",
            "commit",
            "--allow-empty",
            "-m",
            "fixture",
        ],
        cwd=checkout,
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    subprocess.run(
        [
            "git",
            "remote",
            "add",
            "origin",
            f"https://github.com/{repo}.git",
        ],
        cwd=checkout,
        check=True,
    )
