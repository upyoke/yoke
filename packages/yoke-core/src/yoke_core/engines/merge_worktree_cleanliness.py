"""Conservative cleanup of disposable ignored worktree caches."""

from __future__ import annotations

import shutil
import sys
from pathlib import Path, PurePosixPath
from typing import Any, Callable


_DISPOSABLE_DIR_NAMES = frozenset(
    {
        "__pycache__",
        ".mypy_cache",
        ".next",
        ".nox",
        "node_modules",
        ".pytest_cache",
        ".ruff_cache",
        ".tox",
        ".venv",
        ".vite",
    }
)
_DISPOSABLE_FILE_NAMES = frozenset({".coverage", "next-env.d.ts"})


def _cache_root(relative_path: str) -> PurePosixPath | None:
    path = PurePosixPath(relative_path.rstrip("/"))
    if path.is_absolute() or not path.parts or ".." in path.parts:
        return None
    for index, part in enumerate(path.parts):
        if part in _DISPOSABLE_DIR_NAMES or part.endswith(".egg-info"):
            return PurePosixPath(*path.parts[: index + 1])
        if part == "build" and (index == 0 or path.parts[0] == "packages"):
            return PurePosixPath(*path.parts[: index + 1])
    if len(path.parts) == 1 and path.name in _DISPOSABLE_FILE_NAMES:
        return path
    return None


def _status(run_git: Callable[..., Any], path: Path) -> Any:
    return run_git(
        [
            "-C",
            str(path),
            "status",
            "--porcelain",
            "--ignored=matching",
            "--untracked-files=all",
        ],
        cwd=str(path),
        capture=True,
    )


def clean_after_disposable_cache_removal(
    run_git: Callable[..., Any], worktree_path: str | Path
) -> bool:
    """Remove only known ignored caches, then prove the worktree is empty.

    Tracked changes, untracked files, quoted/unparseable paths, and every
    unknown ignored path fail closed. The active Python environment is also
    protected so cleanup cannot unlink the interpreter running the merge.
    """
    root = Path(worktree_path).resolve()
    first = _status(run_git, root)
    if first.returncode != 0:
        return False
    cache_roots: set[PurePosixPath] = set()
    for line in (first.stdout or "").splitlines():
        if not line.startswith("!! "):
            return False
        relative = line[3:]
        cache_root = _cache_root(relative)
        if cache_root is None:
            return False
        cache_roots.add(cache_root)

    executable = Path(sys.executable).resolve()
    for relative in sorted(cache_roots, key=lambda item: len(item.parts), reverse=True):
        candidate = root.joinpath(*relative.parts)
        try:
            resolved = candidate.resolve(strict=False)
            if not resolved.is_relative_to(root):
                return False
            if executable == resolved or executable.is_relative_to(resolved):
                return False
            if candidate.is_symlink() or candidate.is_file():
                candidate.unlink(missing_ok=True)
            elif candidate.is_dir():
                shutil.rmtree(candidate)
        except OSError:
            return False

    final = _status(run_git, root)
    return final.returncode == 0 and not (final.stdout or "").strip()


__all__ = ["clean_after_disposable_cache_removal"]
