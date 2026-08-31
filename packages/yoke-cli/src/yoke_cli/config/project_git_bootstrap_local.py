"""Local git init, nested-repo refusal, and starter gitignore for bootstrap."""

from __future__ import annotations

from pathlib import Path
from typing import Callable

from yoke_cli.config import project_git_prerequisite
from yoke_cli.config import project_local_git
from yoke_cli.config import project_publish_support as pub
from yoke_cli.config.project_git_process import NetworkGitBoundaryError
from yoke_cli.config.project_onboard_support import ProjectOnboardError
from yoke_cli.config.project_worktrees_ignore import WORKTREES_IGNORE_ENTRY
from yoke_contracts.project_git_bootstrap import GIT_BOOTSTRAP_USAGE

STARTER_GITIGNORE = "\n".join((
    "# Yoke lanes",
    WORKTREES_IGNORE_ENTRY,
    "",
    "# Dependencies and build output",
    "node_modules/",
    ".venv/",
    "venv/",
    "__pycache__/",
    "*.py[cod]",
    "dist/",
    "build/",
    "*.egg-info/",
    "",
    "# OS",
    ".DS_Store",
    "Thumbs.db",
    "",
    "# Large / binary working-folder assets",
    "*.iso",
    "*.dmg",
    "*.zip",
    "*.tar",
    "*.tar.gz",
    "*.tgz",
    "*.7z",
    "*.rar",
    "*.mp4",
    "*.mov",
    "*.mkv",
    "*.mp3",
    "*.wav",
    "*.psd",
    "*.ai",
)) + "\n"

_InitFn = Callable[[Path, str], bool]


def refuse_nested_checkout(root: Path) -> None:
    """Refuse when ``root`` would nest a repo inside another worktree."""

    probe = root
    while not probe.is_dir():
        parent = probe.parent
        if parent == probe:
            return
        probe = parent
    project_git_prerequisite.require_git_available()
    try:
        result = project_local_git.run(probe, "rev-parse", "--show-toplevel")
    except (OSError, NetworkGitBoundaryError) as exc:
        raise ProjectOnboardError(
            "could not inspect enclosing git state for "
            f"{root}. {GIT_BOOTSTRAP_USAGE}"
        ) from exc
    if result.returncode != 0:
        return
    toplevel = Path(result.stdout.strip())
    try:
        if toplevel.resolve() == root.resolve(strict=False):
            return
    except OSError:
        pass
    raise ProjectOnboardError(
        f"checkout {root} is inside git worktree {toplevel}; refuse rather "
        "than nest a repository. Move the folder out, or run "
        f"`yoke project git bootstrap {toplevel} --yes` on the enclosing "
        "worktree."
    )


def prepare_checkout(
    root: Path,
    default_branch: str,
    *,
    init_repo: bool = True,
    init_repo_if_needed: _InitFn = pub.init_repo_if_needed,
    ensure_initial_commit: Callable[[Path, str], None] = pub.ensure_initial_commit,
) -> dict[str, bool | list[str]]:
    """Init at the exact root, write a starter gitignore, commit if new.

    Returns a small dict so the public receipt type can live on the
    orchestrating module without an import cycle.
    """

    refuse_nested_checkout(root)
    skipped: list[str] = []
    if not init_repo:
        if not pub.is_git_repo(root):
            raise ProjectOnboardError(
                f"checkout {root} is not a git repository; omit --no-init "
                f"or run `{GIT_BOOTSTRAP_USAGE}` without --no-init."
            )
        skipped.append("init")
        return {
            "initialized": False,
            "gitignore_written": False,
            "committed": False,
            "skipped": skipped,
        }
    root.mkdir(parents=True, exist_ok=True)
    inited = bool(init_repo_if_needed(root, default_branch))
    if not inited:
        skipped.append("init")
        return {
            "initialized": False,
            "gitignore_written": False,
            "committed": False,
            "skipped": skipped,
        }
    gitignore_written = False
    ignore = root / ".gitignore"
    if not ignore.exists():
        ignore.write_text(STARTER_GITIGNORE, encoding="utf-8")
        gitignore_written = True
    committed = False
    if pub.is_git_repo(root):
        ensure_initial_commit(root, default_branch)
        committed = True
    return {
        "initialized": True,
        "gitignore_written": gitignore_written,
        "committed": committed,
        "skipped": skipped,
    }


__all__ = [
    "STARTER_GITIGNORE",
    "prepare_checkout",
    "refuse_nested_checkout",
]
