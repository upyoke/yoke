"""An uninstalled registered checkout still has safe, explicit cleanup."""

import json
import subprocess

import pytest

from yoke_cli.config import writer, machine_config
from yoke_cli.project_install import uninstall_commit
from yoke_cli.project_install.uninstall import uninstall
from yoke_cli.project_install.files import ProjectInstallError


def git(root, *args):
    return subprocess.run(
        ["git", "-C", str(root), *args], capture_output=True, text=True, check=True
    ).stdout.strip()


@pytest.fixture
def registered(tmp_path, monkeypatch):
    config = tmp_path / "machine/config.json"
    monkeypatch.setenv("YOKE_MACHINE_HOME", str(config.parent))
    writer.set_connection(
        "prod",
        transport="https",
        api_url="https://fixture.invalid",
        token="fixture",
        path=config,
    )
    root = tmp_path / "checkout"
    root.mkdir()
    git(root, "init", "-b", "main")
    git(root, "config", "user.name", "Fixture")
    git(root, "config", "user.email", "fixture@example.com")
    (root / "app.txt").write_text("owned source\n")
    git(root, "add", "app.txt")
    git(root, "commit", "-m", "Initial fixture")
    writer.register_project(root, 7, path=config)
    monkeypatch.setattr(uninstall_commit, "dispatch", lambda *a: {"value": "main"})
    return root, config


def test_dirty_refusal_preserves_mapping_then_clean_retry_removes_only_it(registered):
    root, config = registered
    original = json.loads(config.read_text())
    before = git(root, "rev-parse", "HEAD")
    cause = root / "qa-owned-disposal-check.txt"
    cause.write_text("owned refusal cause\n")
    with pytest.raises(ProjectInstallError, match="project_uninstall_dirty_tree"):
        uninstall(root, config_path=config)
    assert json.loads(config.read_text()) == original
    assert cause.exists()
    cause.unlink()

    report = uninstall(root, config_path=config)

    assert report["outcome"] == "complete"
    assert report["files_removed"] == []
    assert machine_config.project_id(root, config) is None
    expected = {**original, "connection_projects": {"prod": []}}
    assert json.loads(config.read_text()) == expected
    assert (root / "app.txt").read_text() == "owned source\n"
    assert git(root, "rev-parse", "HEAD") == before


def test_missing_manifest_never_authorizes_deleting_unknown_installed_files(registered):
    root, config = registered
    (root / ".yoke").mkdir()
    (root / ".yoke/custom.txt").write_text("unowned\n")
    git(root, "add", ".yoke/custom.txt")
    git(root, "commit", "-m", "Keep operator content")
    before = config.read_bytes()
    with pytest.raises(ProjectInstallError, match="project_uninstall_manifest_missing"):
        uninstall(root, config_path=config)
    assert config.read_bytes() == before
    assert (root / ".yoke/custom.txt").read_text() == "unowned\n"


def test_shared_connection_registration_is_preserved(registered):
    root, config = registered
    writer.set_connection(
        "other",
        transport="https",
        api_url="https://other.invalid",
        token="fixture",
        path=config,
    )
    writer.set_active_env("other", path=config)
    writer.register_project(root, 8, path=config)
    writer.set_active_env("prod", path=config)
    before = config.read_bytes()
    with pytest.raises(
        ProjectInstallError,
        match="project_uninstall_registration_project_identity_changed",
    ):
        uninstall(root, config_path=config)
    assert config.read_bytes() == before
