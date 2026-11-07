"""HEAD-moving hooks keep a source checkout's generated views current."""

from __future__ import annotations

from pathlib import Path
from typing import List

import pytest

from yoke_cli.commands import git_hook
from yoke_cli.main import main as cli_main
from yoke_contracts.git_hook_markers import HEAD_RECORDING_GIT_HOOKS


@pytest.fixture
def recorded(monkeypatch, tmp_path) -> List[Path]:
    roots: List[Path] = []
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(git_hook, "_checkout_project", lambda: "yoke")
    monkeypatch.setattr(git_hook, "project_snapshot_sync", lambda _args: 0)
    monkeypatch.setattr(
        git_hook, "refresh_source_installed_views", lambda root: roots.append(root)
    )
    return roots


@pytest.mark.parametrize("hook", HEAD_RECORDING_GIT_HOOKS)
def test_every_head_moving_hook_refreshes_from_the_working_tree(
    recorded, tmp_path, hook
) -> None:
    assert cli_main(["git", hook, "a" * 40, "b" * 40, "0"]) == 0
    assert recorded == [tmp_path]


def test_refresh_failure_warns_and_still_records(monkeypatch, tmp_path, capsys) -> None:
    monkeypatch.chdir(tmp_path)
    synced: List[List[str]] = []
    monkeypatch.setattr(git_hook, "_checkout_project", lambda: "yoke")
    monkeypatch.setattr(git_hook, "project_snapshot_sync", synced.append)

    def refuse(root: Path) -> List[str]:
        raise OSError("disk full")

    monkeypatch.setattr(git_hook, "refresh_source_installed_views", refuse)

    assert cli_main(["git", "post-merge", "0"]) == 0

    err = capsys.readouterr().err
    assert "installed-layout views not refreshed (disk full)" in err
    assert "yoke dev setup" in err
    assert synced == [["--hook", "post-merge", "--head-only", "--project", "yoke"]]
