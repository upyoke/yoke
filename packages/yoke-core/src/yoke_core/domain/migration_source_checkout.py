"""Git checkout validation for committed migration sources."""

from __future__ import annotations

from pathlib import Path
import subprocess
from typing import Any

from yoke_core.domain.migration_apply_resolve import _resolve_repo_path
from yoke_core.domain.migration_manifest_validation import MigrationManifestError


def require_clean_git_checkout(root: Path) -> None:
    if git_capture(root, ["rev-parse", "--is-inside-work-tree"]) != "true":
        raise MigrationManifestError(f"not a git worktree: {root}")
    status = git_capture(root, ["status", "--porcelain", "--untracked-files=all"])
    if status:
        raise MigrationManifestError(
            "itemless governed migration requires a clean source worktree"
        )


def require_registered_checkout(
    control_conn: Any,
    root: Path,
    project: str,
) -> None:
    registered = _resolve_repo_path(control_conn, project).resolve()
    if git_common_dir(root) != git_common_dir(registered):
        raise MigrationManifestError(
            f"worktree {root} is not attached to registered checkout {registered}"
        )


def git_common_dir(root: Path) -> Path:
    raw = git_capture(root, ["rev-parse", "--git-common-dir"])
    path = Path(raw)
    return (root / path).resolve() if not path.is_absolute() else path.resolve()


def require_tracked(root: Path, relative: Path) -> None:
    result = git_run(root, ["ls-files", "--error-unmatch", relative.as_posix()])
    if result.returncode != 0:
        raise MigrationManifestError(
            f"migration source is not tracked at HEAD: {relative.as_posix()}"
        )


def git_capture(root: Path, argv: list[str]) -> str:
    result = git_run(root, argv)
    if result.returncode != 0:
        raise MigrationManifestError(
            f"git {' '.join(argv)} failed in {root}: {result.stderr.strip()}"
        )
    return result.stdout.strip()


def git_run(root: Path, argv: list[str]) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            ["git", "-C", str(root), *argv],
            check=False,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
        raise MigrationManifestError(f"git source validation failed: {exc}") from exc


__all__ = [
    "git_capture",
    "git_common_dir",
    "git_run",
    "require_clean_git_checkout",
    "require_registered_checkout",
    "require_tracked",
]
