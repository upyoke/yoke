"""Yoke lane worktrees a project uninstall must settle before it changes anything.

A lane is a linked Git worktree inside the checkout's lanes directory
(``settings.worktrees_dir``, default ``.worktrees``). Its branch holds the
lane's commits, so removing a clean lane loses nothing; a lane with
uncommitted changes is never removed. Every refusal fires before the
uninstall removes a file or makes its commit.
"""

from __future__ import annotations

from pathlib import Path

from yoke_contracts.machine_config import reader as machine_config
from yoke_cli.project_install import checkout_gate, owned_cleanup
from yoke_contracts.project_contract.install_error import ProjectInstallError


def settle(root: Path, config_path, *, remove: bool, check: bool = False) -> dict:
    """Remove clean lanes when *remove*; otherwise refuse while any lane exists.

    *check* runs every refusal and removes nothing. The report names each
    removed lane and the branch it leaves behind in the checkout.
    """
    report: dict = {"removed": [], "branches_kept": []}
    if not checkout_gate.is_git_checkout(root):
        return report  # Lanes are Git worktrees; a plain folder has none.
    lanes_dir = owned_cleanup.lanes_dir(root, machine_config.load_config(config_path))
    lanes = {
        lane: branch
        for lane, branch in _linked_worktrees(root).items()
        if lane.is_relative_to(lanes_dir)
    }
    if not lanes:
        return report
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
    if check:
        return report
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
    report["removed"] = [str(lane) for lane in lanes]
    report["branches_kept"] = [branch for branch in lanes.values() if branch]
    return report


def kept_branches_warning(root: Path, branches: list[str]) -> list[str]:
    """Name the lane branches left in the checkout and how to delete them."""
    if not branches:
        return []
    return [
        f"project_uninstall_lane_branches_kept: {', '.join(branches)} stay in "
        f"{root} with their commits; delete each you no longer need with "
        f"`git -C {root} branch -D <branch>`."
    ]


def _linked_worktrees(root: Path) -> dict[Path, str]:
    """Each linked worktree and its branch name (empty when detached)."""
    listed = checkout_gate.run_git(root, "worktree", "list", "--porcelain", "-z")
    if listed.returncode != 0:
        detail = listed.stderr.strip() or "git worktree list failed"
        raise ProjectInstallError(
            f"project_uninstall_worktrees_unread: {detail}. Repair git in {root}, "
            "then retry project uninstall."
        )
    members: dict[Path, str] = {}
    current = None
    for field in listed.stdout.split("\0"):
        if field.startswith("worktree "):
            current = Path(field[9:]).resolve()
            members[current] = ""
        elif field.startswith("branch ") and current is not None:
            members[current] = field[7:].removeprefix("refs/heads/")
    members.pop(root.resolve(), None)
    return members
