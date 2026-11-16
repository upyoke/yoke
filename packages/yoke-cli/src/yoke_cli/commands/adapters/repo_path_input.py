"""Turn repo paths typed on Windows into the POSIX repo-relative form claims use.

Claims, surveys and evidence name files by project-relative POSIX paths, and
the server compares them byte for byte. On Windows an operator naturally
types ``packages\\app\\main.py`` or a drive-letter path such as
``C:\\work\\repo\\packages\\app\\main.py``. This module rewrites both into
``packages/app/main.py`` on the client, before any network call, and refuses
paths a Windows checkout cannot hold as distinct files:

* a segment that is a reserved device name (``CON``, ``NUL``, ``COM1`` ...),
  ends in a dot or space, or holds a character Windows forbids;
* two paths that differ only by letter case, or a path whose case differs
  from the tracked file it names (the registry would not match it).

On other operating systems paths pass through unchanged; the shared
claim-path checks still refuse backslashes there.
"""

from __future__ import annotations

import ntpath
import os
import re
import subprocess
from pathlib import Path
from typing import Iterable, Sequence

PATH_WINDOWS_RESERVED = "path_windows_reserved"
PATH_CASE_COLLISION = "path_case_collision"
PATH_OUTSIDE_REPOSITORY = "path_not_project_relative"

_DRIVE_ABSOLUTE = re.compile(r"^[A-Za-z]:[\\/]")
_RESERVED_STEMS = frozenset(
    {"con", "prn", "aux", "nul", "conin$", "conout$"}
    | {f"{name}{digit}" for name in ("com", "lpt") for digit in "123456789¹²³"}
)
_FORBIDDEN_CHARS = frozenset('<>:"|?*')


class RepoPathInputError(ValueError):
    """A typed path cannot name one file in a Windows checkout."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def normalize_repo_paths(
    paths: Sequence[str],
    *,
    repo_root: str | Path | None = None,
    windows: bool | None = None,
) -> list[str]:
    """Return *paths* as POSIX repo-relative paths, or raise a named refusal."""
    if not (_on_windows() if windows is None else windows):
        return list(paths)
    root = _repo_root(repo_root) if any(_is_absolute(p) for p in paths) else None
    selected = [_relative_posix(path, root) for path in paths]
    reserved = [path for path in selected if _reserved_segments(path)]
    if reserved:
        raise RepoPathInputError(PATH_WINDOWS_RESERVED, _reserved_message(reserved))
    collisions = _input_collisions(selected) or _tracked_mismatches(
        selected, repo_root
    )
    if collisions:
        raise RepoPathInputError(PATH_CASE_COLLISION, _collision_message(collisions))
    return selected


def _on_windows() -> bool:
    return os.name == "nt"


def _is_absolute(path: str) -> bool:
    text = path.strip()
    return bool(_DRIVE_ABSOLUTE.match(text)) or text.startswith(("\\\\", "//"))


def _relative_posix(raw: str, root: str | None) -> str:
    text = raw.strip()
    if not _is_absolute(text):
        return text.replace("\\", "/")
    if root is None:
        raise RepoPathInputError(
            PATH_OUTSIDE_REPOSITORY,
            f"{raw} is an absolute path and this directory is not inside a git "
            "checkout. Run the command from the repository, or pass the path "
            "relative to the repository root.",
        )
    folded_root = ntpath.normcase(ntpath.normpath(root)).rstrip("\\")
    folded = ntpath.normcase(ntpath.normpath(text))
    if not folded.startswith(folded_root + "\\"):
        raise RepoPathInputError(
            PATH_OUTSIDE_REPOSITORY,
            f"{raw} is outside the repository at {root}; outside-repo paths are "
            "not claimable. Pass a path inside the repository.",
        )
    relative = ntpath.normpath(text)[len(ntpath.normpath(root).rstrip("\\")) + 1 :]
    return relative.replace("\\", "/")


def _reserved_segments(path: str) -> list[str]:
    bad = []
    for segment in path.split("/"):
        if not segment or segment in (".", ".."):
            continue
        stem = segment.split(".", 1)[0].rstrip(" ").casefold()
        if (
            stem in _RESERVED_STEMS
            or segment[-1] in ". "
            or any(char in _FORBIDDEN_CHARS for char in segment)
        ):
            bad.append(segment)
    return bad


def _input_collisions(paths: Iterable[str]) -> list[tuple[str, str]]:
    seen: dict[str, str] = {}
    collisions = []
    for path in paths:
        other = seen.setdefault(path.casefold(), path)
        if other != path:
            collisions.append((path, other))
    return collisions


def _tracked_mismatches(
    paths: Sequence[str], repo_root: str | Path | None
) -> list[tuple[str, str]]:
    """Pair each path with the differently-cased tracked file it would open."""
    root = _repo_root(repo_root)
    if root is None or not paths:
        return []
    try:
        proc = subprocess.run(
            ["git", "-C", root, "ls-files", "-z", "--", *(f":(icase){p}" for p in paths)],
            capture_output=True,
            check=False,
        )
    except OSError:
        return []
    if proc.returncode != 0:
        return []
    tracked: dict[str, list[str]] = {}
    for name in proc.stdout.decode("utf-8", errors="replace").split("\0"):
        if name:
            tracked.setdefault(name.casefold(), []).append(name)
    mismatches = []
    for path in paths:
        names = tracked.get(path.casefold(), [])
        if names and path not in names:
            mismatches.append((path, names[0]))
    return mismatches


def _repo_root(repo_root: str | Path | None) -> str | None:
    from yoke_cli.project_snapshot.scanner import (
        ProjectSnapshotScanError,
        resolve_repo_root,
    )

    try:
        return str(resolve_repo_root(repo_root))
    except (ProjectSnapshotScanError, OSError, ValueError):
        return None


def _reserved_message(paths: Sequence[str]) -> str:
    return (
        "these paths use names a Windows checkout cannot hold (reserved device "
        "names such as CON or NUL, a trailing dot or space, or one of "
        f'<>:"|?*): {", ".join(paths)}. Rename the file in the repository, '
        "then claim the new path."
    )


def _collision_message(pairs: Sequence[tuple[str, str]]) -> str:
    named = ", ".join(f"{typed} (matches {other})" for typed, other in pairs)
    return (
        "these paths differ only by letter case from another path, and a "
        f"Windows checkout treats them as one file: {named}. Use the exact "
        "spelling the repository tracks, once."
    )


__all__ = [
    "PATH_CASE_COLLISION",
    "PATH_WINDOWS_RESERVED",
    "RepoPathInputError",
    "normalize_repo_paths",
]
