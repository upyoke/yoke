"""The optional item-base config write never blocks lane creation."""

from __future__ import annotations

import subprocess
from pathlib import Path

from yoke_contracts.project_contract.file_line_policy import item_base_config_key
from yoke_core.domain import worktree_provision
from yoke_core.domain.worktree_create_plan import WorktreeCreationEntry


def _git(cwd: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", "-C", str(cwd), *args],
        capture_output=True,
        text=True,
    )


def test_failed_item_base_write_still_creates_worktree(
    monkeypatch, tmp_path: Path
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q",
         "--allow-empty", "-m", "seed")
    real_run = worktree_provision._run
    config_key = item_base_config_key("YOK-1")

    def run_with_locked_config(cmd, *args, **kwargs):
        if cmd[-2:-1] == [config_key] and "--get" not in cmd:
            return subprocess.CompletedProcess(
                cmd, 255, stdout="",
                stderr="error: could not lock config file .git/config: File exists\n",
            )
        return real_run(cmd, *args, **kwargs)

    monkeypatch.setattr(worktree_provision, "_run", run_with_locked_config)
    lane = tmp_path / "lane"
    entry = WorktreeCreationEntry(branch="YOK-1", path=str(lane))

    err = worktree_provision.create_worktree_lane(entry, str(repo), "main")

    assert err is None
    assert (lane / ".git").exists()
    assert _git(repo, "config", "--get", config_key).returncode != 0
