"""Yoke lane worktrees a project uninstall must settle before it changes anything.

A lane is a linked Git worktree inside the checkout's lanes directory
(``settings.worktrees_dir``, default ``.worktrees``). Its branch holds the
lane's commits, so removing a clean lane loses nothing; a lane with
uncommitted changes is never removed. Every refusal fires before the
uninstall removes a file or makes its commit.
"""

from __future__ import annotations

from pathlib import Path

from yoke_cli.config import machine_config
from yoke_cli.project_install import checkout_gate, owned_cleanup
from yoke_cli.project_install.files import ProjectInstallError


def settle(root: Path, config_path, *, remove: bool) -> list[str]:
    """Remove clean lanes when *remove*; otherwise refuse while any lane exists."""
    lanes_dir = owned_cleanup.lanes_dir(root, machine_config.load_config(config_path))
    lanes = [lane for lane in _linked_worktrees(root) if lane.is_relative_to(lanes_dir)]
    if not lanes:
        return []
    named = ", ".join(str(lane) for lane in lanes)
    if not remove:
        raise ProjectInstallError(
            f"project_uninstall_open_lanes: {named} are Yoke lane worktrees of "
            "this project's open items. Finish or cancel those items, or commit "
            "each lane's work and run `git worktree remove <lane>`, then retry "
            "project uninstall. `yoke uninstall` removes clean lanes itself."
        )
    dirty = [lane for lane in lanes if checkout_gate.porcelain(lane)]
    if dirty:
        raise ProjectInstallError(
            "project_uninstall_lane_dirty: "
            + ", ".join(str(lane) for lane in dirty)
            + " hold uncommitted changes, so nothing was uninstalled. Commit or "
            "discard them in each lane (its branch keeps the commits), then retry."
        )
    for lane in lanes:
        removed = checkout_gate.run_git(root, "worktree", "remove", str(lane))
        if removed.returncode != 0:
            detail = removed.stderr.strip() or removed.stdout.strip()
            raise ProjectInstallError(
                f"project_uninstall_lane_remove_failed: git could not remove {lane} "
                f"({detail}). Unlock or repair it with `git worktree remove {lane}`, "
                "then retry."
            )
    if lanes_dir.is_dir() and not any(lanes_dir.iterdir()):
        lanes_dir.rmdir()
    return [str(lane) for lane in lanes]


def _linked_worktrees(root: Path) -> list[Path]:
    listed = checkout_gate.run_git(root, "worktree", "list", "--porcelain", "-z")
    if listed.returncode != 0:
        detail = listed.stderr.strip() or "git worktree list failed"
        raise ProjectInstallError(
            f"project_uninstall_worktrees_unread: {detail}. Repair git in {root}, "
            "then retry project uninstall."
        )
    members = [
        Path(line[9:]).resolve()
        for line in listed.stdout.split("\0")
        if line.startswith("worktree ")
    ]
    return [member for member in members if member != root.resolve()]
