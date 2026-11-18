"""Local ``.yoke`` views a complete project uninstall removes or names.

The seeded ``.yoke/.gitignore`` hides generated views. A complete uninstall
deletes that policy, so it first removes the regenerable board views, then
names every ``.yoke`` path still left untracked so nothing appears silently.
"""

from __future__ import annotations

import shutil
from pathlib import Path

from yoke_cli.project_install import checkout_gate
from yoke_cli.project_install.files import ProjectInstallError

YOKE_DIR = ".yoke"
STRATEGY_DIR = ".yoke/strategy/"


def remove_board_views(root: Path) -> list[str]:
    """Delete generated ``.yoke/BOARD.md*`` views; any board render recreates them."""
    removed: list[str] = []
    for view in sorted((root / YOKE_DIR).glob("BOARD.md*")):
        if _tracked(root, view.relative_to(root).as_posix()):
            continue  # Project content: the operator chose to version it.
        if view.is_dir() and not view.is_symlink():
            shutil.rmtree(view)
        else:
            view.unlink()
        removed.append(view.relative_to(root).as_posix())
    return removed


def kept_warnings(root: Path) -> list[str]:
    """Name every ``.yoke`` path the uninstall leaves on disk untracked."""
    kept = _untracked(root)
    strategy = [path for path in kept if path.startswith(STRATEGY_DIR)]
    other = [path for path in kept if not path.startswith(STRATEGY_DIR)]
    warnings: list[str] = []
    if strategy:
        warnings.append(
            "project_uninstall_strategy_views_kept: "
            + ", ".join(strategy)
            + " stay on disk untracked as your planning content; commit or "
            "delete them."
        )
    if other:
        warnings.append(
            "project_uninstall_local_files_kept: "
            + ", ".join(other)
            + " stay on disk untracked; commit or delete them."
        )
    return warnings


def _tracked(root: Path, rel: str) -> bool:
    if not checkout_gate.is_git_checkout(root):
        return False
    listed = checkout_gate.run_git(root, "ls-files", "--", rel)
    return listed.returncode != 0 or bool(listed.stdout.strip())


def _untracked(root: Path) -> list[str]:
    if not checkout_gate.is_git_checkout(root):
        strategy = root / STRATEGY_DIR
        return sorted(
            path.relative_to(root).as_posix()
            for path in strategy.rglob("*")
            if path.is_file()
        ) if strategy.is_dir() else []
    listed = checkout_gate.run_git(
        root, "ls-files", "-z", "--others", "--exclude-standard", "--", YOKE_DIR
    )
    if listed.returncode != 0:
        detail = listed.stderr.strip() or listed.stdout.strip() or "git ls-files failed"
        raise ProjectInstallError(
            f"project_uninstall_untracked_paths_unread: {detail}. The Yoke layer "
            f"was removed and committed; run git status in {root} to see the "
            ".yoke paths left untracked."
        )
    return sorted(path for path in listed.stdout.split("\0") if path)
