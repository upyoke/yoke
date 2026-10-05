"""Project uninstall owns its removal commit without touching operator work."""

import subprocess

import pytest

from yoke_cli.project_install.uninstall import uninstall
from yoke_cli.project_install.files import ProjectInstallError
from yoke_core.domain.project_install_test_helpers import make_bundle
from yoke_cli.project_install.bundle_apply import apply_bundle
from yoke_cli.project_install import uninstall_commit


def git(root, *args):
    result = subprocess.run(
        ["git", "-C", str(root), *args], capture_output=True, text=True, check=True
    )
    return result.stdout.strip()


@pytest.fixture
def checkout(tmp_path, monkeypatch):
    monkeypatch.setattr(uninstall_commit, "dispatch", lambda *a: {"value": "main"})
    root = tmp_path / "repo"
    root.mkdir()
    git(root, "init", "-b", "main")
    git(root, "config", "user.name", "Test")
    git(root, "config", "user.email", "test@example.com")
    (root / ".gitignore").write_text(".yoke/install-manifest.json\n")
    (root / "app.txt").write_text("operator code\n")
    apply_bundle(root, make_bundle(), source="test")
    git(root, "add", "-A")
    git(root, "commit", "--no-verify", "-m", "Install operating layer")
    return root


def test_removal_commits_and_leaves_operator_code(checkout):
    before = git(checkout, "rev-parse", "HEAD")
    report = uninstall(checkout)
    assert report["commit"]["status"] == "created"
    assert git(checkout, "rev-parse", "HEAD") != before
    assert git(checkout, "log", "-1", "--format=%s") == "Uninstall Yoke operating layer"
    assert (checkout / "app.txt").read_text() == "operator code\n"
    assert not git(checkout, "status", "--porcelain")


def test_staged_operator_change_refuses_before_removal(checkout):
    target = checkout / "app.txt"
    target.write_text("operator changed it\n")
    git(checkout, "add", "app.txt")
    before = git(checkout, "diff", "--cached")
    with pytest.raises(ProjectInstallError, match="project_uninstall_dirty_tree"):
        uninstall(checkout)
    assert git(checkout, "diff", "--cached") == before
    assert (checkout / ".yoke/install-manifest.json").is_file()


@pytest.mark.parametrize("branch", ["feature", None])
def test_off_default_branch_refuses_before_removal(checkout, branch):
    if branch:
        git(checkout, "switch", "-c", branch)
    else:
        git(checkout, "switch", "--detach")
    before = git(checkout, "rev-parse", "HEAD")
    with pytest.raises(
        ProjectInstallError, match="project_uninstall_checkout_refused"
    ) as exc:
        uninstall(checkout)
    assert "git switch main" in str(exc.value)
    assert "--force" not in str(exc.value)
    assert git(checkout, "rev-parse", "HEAD") == before
    assert (checkout / ".yoke/install-manifest.json").is_file()


def test_project_branch_and_custom_connection_are_read(checkout, monkeypatch, tmp_path):
    git(checkout, "switch", "-c", "trunk")
    calls = []
    config = tmp_path / "config.json"

    def dispatch(*args):
        calls.append(args)
        return {"value": "trunk"}

    monkeypatch.setattr(uninstall_commit, "dispatch", dispatch)
    assert uninstall(checkout, config_path=config)["commit"]["status"] == "created"
    assert calls == [
        ("projects.get", {"project": "7", "field": "default_branch"}, config)
    ]


def test_unreadable_project_branch_preserves_install(checkout, monkeypatch):
    def fail(*args):
        raise RuntimeError("connection unavailable")

    monkeypatch.setattr(uninstall_commit, "dispatch", fail)
    with pytest.raises(
        ProjectInstallError, match="project_uninstall_default_branch_unavailable"
    ):
        uninstall(checkout)
    assert (checkout / ".yoke/install-manifest.json").is_file()
