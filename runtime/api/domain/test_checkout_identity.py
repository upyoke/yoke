"""Git determines the primary checkout for every linked-worktree layout."""

from __future__ import annotations

import subprocess

import pytest

from yoke_cli.config.checkout_context import resolve_repo_root_from_cwd
from yoke_contracts.machine_config.checkout import main_checkout
from yoke_contracts.machine_config.schema_connections import MachineConfigContractError
from yoke_core.domain.rebuild_board import resolve_main_repo_root
from yoke_core.domain.worktree_paths import resolve_main_root


@pytest.fixture
def checkout(tmp_path):
    root = tmp_path / "main"
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    subprocess.run(
        ["git", "-c", "user.email=test@example.invalid", "-c", "user.name=Test",
         "commit", "-qm", "seed", "--allow-empty"],
        cwd=root, check=True,
    )
    return root.resolve()


@pytest.mark.parametrize("location", [".worktrees/lane", ".claude/worktrees/lane", "../external"])
def test_main_checkout_from_registered_worktree(checkout, location, monkeypatch):
    monkeypatch.delenv("CLAUDE_PROJECT_DIR", raising=False)
    lane = (checkout / location).resolve()
    subprocess.run(
        ["git", "worktree", "add", "-q", "--detach", str(lane)],
        cwd=checkout, check=True,
    )
    nested = lane / "nested"
    nested.mkdir()
    # Git for Windows produces C:/... while native Path strings use backslashes.
    for cwd in (str(nested), nested.as_posix()):
        assert main_checkout(cwd) == checkout
        assert resolve_repo_root_from_cwd(cwd) == str(checkout)
        assert resolve_main_root(cwd=cwd) == str(checkout)
        assert resolve_main_repo_root(cwd) == checkout


def test_checkout_identity_refuses_broken_git_metadata(tmp_path):
    (tmp_path / ".git").write_text("invalid worktree pointer", encoding="utf-8")
    with pytest.raises(MachineConfigContractError, match="checkout_identity_unavailable"):
        resolve_repo_root_from_cwd(str(tmp_path))


def test_checkout_identity_refuses_bare_repo(tmp_path):
    subprocess.run(["git", "init", "--bare", "-q", str(tmp_path)], check=True)
    with pytest.raises(MachineConfigContractError, match="checkout_identity_unavailable"):
        main_checkout(tmp_path)
