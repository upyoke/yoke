"""Windows callers recognize worktree paths recorded from WSL."""

from __future__ import annotations

from yoke_core.domain import verification_tree_binding


def test_wsl_mount_path_translates_to_native_windows_drive() -> None:
    translated = verification_tree_binding._local_worktree_text(
        "/mnt/c/git/hub/yoke/.worktrees/YOK-3930",
        "nt",
    )

    assert translated == "C:/git/hub/yoke/.worktrees/YOK-3930"


def test_non_windows_callers_retain_recorded_path() -> None:
    recorded = "/mnt/c/git/hub/yoke/.worktrees/YOK-3930"

    assert verification_tree_binding._local_worktree_text(recorded, "posix") == recorded


def test_non_wsl_windows_path_is_unchanged() -> None:
    recorded = r"C:\git\hub\yoke\.worktrees\YOK-3930"

    assert verification_tree_binding._local_worktree_text(recorded, "nt") == recorded
