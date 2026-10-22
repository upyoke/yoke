"""Onboarded projects uninstall completely, and a partial uninstall retries."""

import json
import os

import pytest

from yoke_cli.config import machine_config, project_onboard_apply, writer
from yoke_cli.project_install import files, runner, uninstall_commit
from yoke_cli.project_install.uninstall import uninstall
from yoke_core.domain.project_install_test_helpers import (
    DEFAULT_CONTRACT_FILES,
    contract_entry,
    make_bundle,
)
from runtime.api.cli.project_uninstall_test_support import git, read_json

IGNORE_POLICY = "BOARD.md\ninstall-manifest.json\ninstall-pending.json\n"


@pytest.fixture
def machine(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("CODEX_HOME", str(home / ".codex"))
    monkeypatch.setenv("YOKE_MACHINE_HOME", str(tmp_path / "machine"))
    monkeypatch.delenv("YOKE_MACHINE_CONFIG_FILE", raising=False)
    monkeypatch.delenv("YOKE_ENV", raising=False)
    launcher = home / "bin/yoke"
    launcher.parent.mkdir()
    launcher.write_text("#!/bin/sh\nexit 0\n")
    launcher.chmod(0o700)
    monkeypatch.setenv("PATH", str(launcher.parent) + os.pathsep + os.environ["PATH"])
    monkeypatch.setattr(uninstall_commit, "dispatch", lambda *a: {"value": "main"})
    bundle = make_bundle(
        contract=[
            *DEFAULT_CONTRACT_FILES,
            contract_entry(".yoke/.gitignore", IGNORE_POLICY),
        ]
    )
    monkeypatch.setattr(runner, "_resolve_bundle", lambda *a, **k: (bundle, "test"))
    config = tmp_path / "machine/config.json"
    writer.set_connection(
        "local",
        transport="https",
        api_url="https://fixture.invalid",
        token="fixture-only",
        path=config,
    )
    root = tmp_path / "checkout"
    root.mkdir()
    git(root, "init", "-b", "main")
    git(root, "config", "user.name", "Fixture")
    git(root, "config", "user.email", "fixture@example.com")
    (root / "app.txt").write_text("operator code\n")
    git(root, "add", "-A")
    git(root, "commit", "--no-verify", "-m", "Operator code")
    return root.resolve(), config


def onboard(root, config, monkeypatch):
    """Run onboarding's final apply with its real mapping write and install."""
    monkeypatch.setattr(
        project_onboard_apply, "applied_report", lambda *a, **k: {"applied": True}
    )
    project_onboard_apply.finish_after_dispatch(
        operation="onboard.project",
        root=root,
        result={"project": {"id": 7, "slug": "demo"}},
        github_adoption={"choice": "skip"},
        config_path=config,
        progress=None,
        github_auth_target="skip",
        scaffold_action="project-install-scaffold",
        reuse_github_auth=True,
        register_mapping=True,
    )
    (root / ".yoke/BOARD.md").write_text("board view\n")
    assert machine_config.project_id(root, config) == 7
    assert not git(root, "status", "--porcelain")


def test_onboarded_checkout_uninstalls_completely(machine, monkeypatch):
    root, config = machine
    onboard(root, config, monkeypatch)
    report = uninstall(root, config_path=config)
    assert report["outcome"] == "complete", report["warnings"]
    assert report["local_cleanup"]["registration"]["reason"] == "owned_exact_entry"
    assert machine_config.project_id(root, config) is None
    assert ".yoke/.gitignore" in report["contract_files_removed"]
    assert not (root / ".yoke/.gitignore").exists()
    assert not files.manifest_path(root).exists()
    assert not git(root, "status", "--porcelain", "--untracked-files=no")
    assert (root / "app.txt").read_text() == "operator code\n"


def test_partial_uninstall_retries_to_completion(machine, monkeypatch):
    root, config = machine
    # The operator mapped the checkout first, so onboarding did not write it.
    writer.register_project(root, 7, path=config)
    onboard(root, config, monkeypatch)
    first = uninstall(root, config_path=config)
    assert first["outcome"] == "partial"
    registration = first["local_cleanup"]["registration"]
    assert registration["reason"] == "registration_ownership_unknown"
    assert f"delete the {root} entry" in registration["recovery"]
    assert str(config) in registration["recovery"]
    # The manifest, ignore policy and local view survive without dirtying git.
    assert files.manifest_path(root).is_file()
    assert (root / ".yoke/.gitignore").read_text() == IGNORE_POLICY
    assert (root / ".yoke/BOARD.md").is_file()
    assert not git(root, "status", "--porcelain")

    # Follow the recovery text: delete the named entry, then rerun.
    payload = read_json(config)
    payload["connection_projects"]["local"] = [
        entry
        for entry in payload["connection_projects"]["local"]
        if entry["checkout"] != str(root)
    ]
    config.write_text(json.dumps(payload, indent=2) + "\n")
    retry = uninstall(root, config_path=config)
    assert retry["outcome"] == "complete", retry["warnings"]
    assert retry["local_cleanup"]["registration"]["reason"] == "no_exact_registration"
    assert ".yoke/.gitignore" in retry["contract_files_removed"]
    assert not files.manifest_path(root).exists()
    assert not git(root, "status", "--porcelain", "--untracked-files=no")
    assert git(root, "log", "-1", "--format=%s") == "Uninstall Yoke operating layer"
