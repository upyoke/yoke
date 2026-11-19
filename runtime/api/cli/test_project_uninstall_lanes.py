"""Open Yoke lanes settle before project uninstall changes anything (feedback 97659)."""

from runtime.api.cli.project_uninstall_owned_cleanup_test_support import (
    installed as installed,
)

import pytest

from yoke_cli.project_install import files
from yoke_cli.project_install.uninstall import uninstall
from runtime.api.cli.project_uninstall_test_support import git


def _lane(root, name="WALKNE-1"):
    lane = root / ".worktrees" / name
    git(root, "worktree", "add", "-b", name, str(lane))
    return lane


def _snapshot(root):
    return git(root, "rev-parse", "HEAD"), files.load_manifest(root)


def test_open_lane_refuses_before_any_change_or_commit(installed):
    root, _, config = installed
    lane = _lane(root)
    before = _snapshot(root)
    with pytest.raises(files.ProjectInstallError, match="project_uninstall_open_lanes"):
        uninstall(root, config_path=config)
    assert _snapshot(root) == before
    assert lane.is_dir()


def test_dirty_lane_refuses_even_when_removal_is_allowed(installed):
    root, _, config = installed
    lane = _lane(root)
    (lane / "work.txt").write_text("uncommitted\n")
    before = _snapshot(root)
    with pytest.raises(files.ProjectInstallError, match="project_uninstall_lane_dirty"):
        uninstall(root, config_path=config, remove_lanes=True)
    assert _snapshot(root) == before
    assert (lane / "work.txt").is_file()


def test_clean_lane_is_removed_and_uninstall_completes_in_one_commit(installed):
    root, _, config = installed
    lane = _lane(root)
    (lane / "work.txt").write_text("committed\n")
    git(lane, "add", "work.txt")
    git(lane, "commit", "--no-verify", "-m", "Lane work")
    head = git(root, "rev-parse", "HEAD")
    report = uninstall(root, config_path=config, remove_lanes=True)
    assert report["outcome"] == "complete", report
    assert report["lanes_removed"] == [str(lane.resolve())]
    assert not (root / ".worktrees").exists()
    # The lane's branch keeps its commit; uninstall adds exactly one commit.
    assert git(root, "log", "-1", "--format=%s", "WALKNE-1") == "Lane work"
    assert git(root, "rev-parse", "HEAD~1") == head
    assert not git(root, "status", "--porcelain")
