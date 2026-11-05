# ruff: noqa: F401, E402
"""Shared setup for tests in this directory."""

import json

import os

from pathlib import Path

import pytest

from yoke_contracts import harness_folder_trust as trust

from yoke_contracts import harness_settings_ledger as ledger

from yoke_contracts.codex_config_posture import parse_config

from yoke_contracts.harness_folder_trust_grant import grant_folder_trust

from yoke_cli.config import machine_config, writer

from yoke_cli.project_install import files, owned_cleanup, uninstall_commit

from yoke_cli.project_install.bundle_apply import apply_bundle

from yoke_cli.project_install.uninstall import uninstall

from yoke_core.domain.project_install_test_helpers import make_bundle

from runtime.api.cli.project_uninstall_test_support import git, read_json


@pytest.fixture
def installed(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("CODEX_HOME", str(home / ".codex"))
    monkeypatch.setenv("YOKE_MACHINE_HOME", str(tmp_path / "machine"))
    launcher = home / "bin/yoke"
    launcher.parent.mkdir()
    launcher.write_text("#!/bin/sh\nexit 0\n")
    launcher.chmod(0o700)
    monkeypatch.setenv("PATH", str(launcher.parent) + os.pathsep + os.environ["PATH"])
    monkeypatch.setattr(uninstall_commit, "dispatch", lambda *a: {"value": "main"})
    config = tmp_path / "machine/config.json"
    writer.set_connection(
        "local",
        transport="https",
        api_url="https://fixture.invalid",
        token="fixture-only",
        path=config,
    )
    roots = [tmp_path / "selected", tmp_path / "other"]
    trust.claude_state_path().write_text('{"projects": {}, "signIn": "keep"}')
    (home / ".codex").mkdir()
    (home / ".codex/config.toml").write_text('# personal\nmodel = "keep"\n')
    trust.cursor_projects_root().mkdir(parents=True)
    for index, root in enumerate(roots, 7):
        root.mkdir()
        git(root, "init", "-b", "main")
        # Keep asynchronous Git maintenance out of exact preservation snapshots.
        git(root, "config", "maintenance.auto", "false")
        git(root, "config", "gc.auto", "0")
        git(root, "config", "user.name", "Fixture")
        git(root, "config", "user.email", "fixture@example.com")
        bundle = make_bundle()
        bundle["project_id"] = index
        apply_bundle(root, bundle, source="fixture")
        writer.register_project(root, index, path=config)
        owned_cleanup.record_registration(root, index, config)
        grant_folder_trust(root)
        git(root, "add", "-A")
        git(root, "commit", "--no-verify", "-m", "Fixture install")
    return roots[0], roots[1], config
