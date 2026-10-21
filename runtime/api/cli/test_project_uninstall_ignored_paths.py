"""Project uninstall commits only what git tracked, and owns its own edits.

Removal deletes the ``.yoke/.gitignore`` that kept the manifest, strategy
views and other local views ignored. The removal commit must still leave
them out of history. The install's own append to ``.yoke/project.config``
must not read as an operator edit at uninstall.
"""

import subprocess

import pytest

from yoke_cli.project_install import uninstall_commit
from yoke_cli.project_install.bundle_apply import apply_bundle
from yoke_cli.project_install.uninstall import uninstall
from yoke_contracts.project_contract.file_line_policy import PROJECT_CONFIG_REL
from yoke_core.domain.project_install_test_helpers import (
    DEFAULT_CONTRACT_FILES,
    contract_entry,
    make_bundle,
    strategy_entry,
)

IGNORED = (".yoke/install-manifest.json", ".yoke/local-view.md")
GITIGNORE = "install-manifest.json\nstrategy/\nlocal-view.md\n"


def git(root, *args):
    result = subprocess.run(
        ["git", "-C", str(root), *args], capture_output=True, text=True, check=True
    )
    return result.stdout.strip()


def _bundle():
    bundle = make_bundle(
        contract=[
            *DEFAULT_CONTRACT_FILES,
            contract_entry(".yoke/.gitignore", GITIGNORE),
            contract_entry(PROJECT_CONFIG_REL, "file_line_limit=350\n"),
        ],
        strategy=[strategy_entry("mission", "Our mission.\n")],
    )
    bundle["managed_markdown"] = {
        "blocks": {"doctrine": "# Yoke doctrine\n"},
        "targets": [{"path": "AGENTS.md", "block": "doctrine"}],
    }
    return bundle


@pytest.fixture
def checkout(tmp_path, monkeypatch):
    monkeypatch.setattr(uninstall_commit, "dispatch", lambda *a: {"value": "main"})
    root = tmp_path / "repo"
    root.mkdir()
    git(root, "init", "-b", "main")
    git(root, "config", "user.name", "Test")
    git(root, "config", "user.email", "test@example.com")
    (root / "app.txt").write_text("operator code\n")
    apply_bundle(root, _bundle(), source="test")
    git(root, "add", "-A")
    git(root, "commit", "--no-verify", "-m", "Install operating layer")
    (root / ".yoke/local-view.md").write_text("local view\n")
    return root


def _strategy_paths(root):
    return sorted(
        str(path.relative_to(root)) for path in (root / ".yoke/strategy").iterdir()
    )


def test_install_left_the_local_views_ignored(checkout):
    assert _strategy_paths(checkout)
    assert not git(checkout, "ls-files", "--", *IGNORED, ".yoke/strategy")
    assert not git(checkout, "status", "--porcelain")


def test_removal_commits_no_ignored_path(checkout):
    strategy = _strategy_paths(checkout)
    install = git(checkout, "rev-parse", "HEAD")
    report = uninstall(checkout)
    assert report["commit"]["status"] == "created"
    committed = git(
        checkout, "log", "--name-only", "--format=", f"{install}..HEAD"
    ).split()
    assert committed
    assert not set(committed) & {*IGNORED, *strategy}
    assert ".yoke/.gitignore" in committed
    assert not set(report["commit"]["paths"]) & {*IGNORED, *strategy}


def test_strategy_documents_stay_on_disk_and_untracked(checkout):
    strategy = _strategy_paths(checkout)
    report = uninstall(checkout)
    assert report["strategy_files_preserved"] == strategy
    assert _strategy_paths(checkout) == strategy
    assert not git(checkout, "ls-files", "--", *strategy)
    assert not git(checkout, "ls-tree", "-r", "--name-only", "HEAD", ".yoke/strategy")


def test_install_appended_project_config_is_removed_without_warning(checkout):
    assert "AGENTS.md" in (checkout / PROJECT_CONFIG_REL).read_text()
    report = uninstall(checkout)
    assert PROJECT_CONFIG_REL in report["contract_files_removed"]
    assert not (checkout / PROJECT_CONFIG_REL).exists()
    assert not [w for w in report["warnings"] if PROJECT_CONFIG_REL in w]


def test_operator_edited_project_config_is_preserved(checkout):
    config = checkout / PROJECT_CONFIG_REL
    config.write_text(config.read_text() + "file_line_limit=500\n")
    git(checkout, "commit", "-am", "Raise the line limit")
    report = uninstall(checkout)
    assert report["contract_files_preserved_modified"] == [PROJECT_CONFIG_REL]
    assert config.read_text().endswith("file_line_limit=500\n")
