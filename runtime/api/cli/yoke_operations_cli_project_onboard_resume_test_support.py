# ruff: noqa: F401, E402
"""Shared setup for tests in this directory."""

from __future__ import annotations

import json

import subprocess

from pathlib import Path

import pytest

from runtime.api.cli.project_onboarding_test_helpers import (
    ProjectOnboardApi,
    seed_remote,
    write_https_config,
)

from runtime.api.cli.project_onboard_github_replay_test_support import (
    CreateRepoReplay,
)

from yoke_cli import main as yoke_operations_cli

from yoke_cli.config import github_publish

from yoke_cli.config import github_publish_transport

from yoke_cli.config import project_clone_resume

from yoke_cli.config import project_clone_support as clone

from yoke_cli.config import project_onboard

from yoke_cli.config import project_onboard_clone

from yoke_cli.config.project_onboard import ProjectOnboardError


def _allow_local_clone(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep local-repo mechanics testable below the GitHub reference boundary."""

    def passthrough(remote_url, **_kwargs):
        return remote_url

    monkeypatch.setattr(
        project_onboard_clone,
        "clean_remote_url",
        passthrough,
    )
    monkeypatch.setattr(clone, "clean_remote_url", passthrough)
    monkeypatch.setattr(
        clone,
        "isolated_remote_config",
        lambda *args, **kwargs: ("core.askPass=",),
    )
