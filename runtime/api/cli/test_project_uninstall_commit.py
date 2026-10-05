"""Project uninstall owns its removal commit without touching operator work."""

import subprocess

import pytest

from yoke_cli.project_install.uninstall import uninstall
from yoke_cli.project_install.files import ProjectInstallError
from yoke_core.domain.project_install_test_helpers import make_bundle
from yoke_cli.project_install.bundle_apply import apply_bundle


def git(root, *args):
    result = subprocess.run(
        ["git", "-C", str(root), *args], capture_output=True, text=True, check=True
    )
    return result.stdout.strip()


@pytest.fixture
def checkout(tmp_path):
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
