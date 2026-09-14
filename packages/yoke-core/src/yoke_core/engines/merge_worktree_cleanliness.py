"""The one residue policy every lane retirement path applies.

A lane directory is disposable when git reports nothing in it except caches
this module can name — build output, virtualenvs, interpreter and tool
caches — or paths the owning project declared through its
``disposable_generated_paths`` policy (see
``yoke_core.engines.lane_residue_declared_paths``). Tracked edits and
untracked files are work. Ignored content that is *not* a named or declared
cache is unknown rather than worthless: a local database, a credential
file, and an operator's scratch notes are all ignored, and none of them is
the repository's to delete.

Landing cleanup, the machine-wide merged-lane sweep, the epic merge
boundary, and the doctor lane report all read this one classification, so a
lane is never disposable to one of them and precious to another.
"""

from __future__ import annotations

import shutil
import sys
from dataclasses import dataclass
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


@dataclass(frozen=True)
class LaneResidueAssessment:
    """Read-only classification of everything git reports in a lane."""

    disposable: bool
    cache_roots: tuple[PurePosixPath, ...] = ()
    precious_paths: tuple[str, ...] = ()
    reason: str = ""


def _cache_root(
    relative_path: str,
    declared_roots: frozenset[PurePosixPath] = frozenset(),
) -> PurePosixPath | None:
    path = PurePosixPath(relative_path.rstrip("/"))
    if path.is_absolute() or not path.parts or ".." in path.parts:
        return None
    for declared in declared_roots:
        if path == declared or path.is_relative_to(declared):
            return declared
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


def _kept(reason: str, precious_paths: tuple[str, ...] = ()) -> LaneResidueAssessment:
    return LaneResidueAssessment(False, precious_paths=precious_paths, reason=reason)


def assess_lane_residue(
    run_git: Callable[..., Any],
    worktree_path: str | Path,
    declared_roots: frozenset[PurePosixPath] = frozenset(),
) -> LaneResidueAssessment:
    """Classify a lane without changing it.

    A disposable result means every status entry is a named or
    project-declared ignored cache, no cache path escapes the lane, and
    none of them contains the interpreter running the cleanup.
    """
    root = Path(worktree_path).resolve()
    current = _status(run_git, root)
    if current.returncode != 0:
        return _kept("worktree status unreadable")

    cache_roots: set[PurePosixPath] = set()
    precious: list[str] = []
    unknown: list[str] = []
    for line in (current.stdout or "").splitlines():
        path = line[3:] if len(line) > 3 else line
        if not line.startswith("!! "):
            precious.append(path)
            continue
        cache_root = _cache_root(path, declared_roots)
        if cache_root is None:
            unknown.append(path)
        else:
            cache_roots.add(cache_root)
    if precious:
        return _kept(
            "unignored changes present: " + ", ".join(precious), tuple(precious)
        )
    if unknown:
        return _kept("unknown ignored files present: " + ", ".join(unknown))

    executable = Path(sys.executable).resolve()
    for relative in cache_roots:
        resolved = root.joinpath(*relative.parts).resolve(strict=False)
        if not resolved.is_relative_to(root):
            return _kept("cache path escapes the worktree")
        if executable == resolved or executable.is_relative_to(resolved):
            return _kept("cache path contains the active interpreter")
    return LaneResidueAssessment(
        True, tuple(sorted(cache_roots, key=lambda item: item.as_posix()))
    )


def clear_lane_residue(
    run_git: Callable[..., Any],
    worktree_path: str | Path,
    declared_roots: frozenset[PurePosixPath] = frozenset(),
) -> LaneResidueAssessment:
    """Remove only named or declared ignored caches, then prove the lane holds nothing.

    The returned assessment is the verdict callers report: disposable means
    the directory is now empty of everything git can see and may be removed
    without force. Anything else names what survived and why.
    """
    root = Path(worktree_path).resolve()
    assessment = assess_lane_residue(run_git, root, declared_roots)
    if not assessment.disposable:
        return assessment
    for relative in sorted(
        assessment.cache_roots, key=lambda item: len(item.parts), reverse=True
    ):
        candidate = root.joinpath(*relative.parts)
        try:
            if not candidate.resolve(strict=False).is_relative_to(root):
                return _kept("cache path escapes the worktree")
            if candidate.is_symlink() or candidate.is_file():
                candidate.unlink(missing_ok=True)
            elif candidate.is_dir():
                shutil.rmtree(candidate)
        except OSError as exc:
            return _kept(f"cache removal refused for {relative.as_posix()}: {exc}")

    final = _status(run_git, root)
    if final.returncode != 0:
        return _kept("worktree status unreadable")
    remaining = (final.stdout or "").strip()
    if remaining:
        return _kept(
            "content remains after cache removal: "
            + ", ".join(line[3:] for line in remaining.splitlines())
        )
    return LaneResidueAssessment(True, assessment.cache_roots)


__all__ = [
    "LaneResidueAssessment",
    "assess_lane_residue",
    "clear_lane_residue",
]
