"""Git-derived changed paths for impacted test selection."""

from __future__ import annotations

import subprocess
from pathlib import Path

from yoke_contracts.project_contract.changed_path_scope import (
    ChangedPathError,
    untracked_paths,
)

#: The ref a change is measured against when the caller names none.
DEFAULT_BASE_REF = "main"


def normalize_changed_path(rel: str) -> str:
    """Repo-relative posix path from one ``git`` name-only line."""
    line = rel.strip().strip('"').replace("\\", "/")
    if line.startswith("./"):
        line = line[2:]
    return line


def _name_only(repo_root: Path, args: list[str]) -> "tuple[str, ...] | None":
    result = subprocess.run(
        ["git", "-C", str(repo_root), *args],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return None
    names: list[str] = []
    for raw in result.stdout.splitlines():
        line = normalize_changed_path(raw)
        if line:
            names.append(line)
    return tuple(names)


def changed_paths(repo_root: Path, base: str) -> tuple[str, ...]:
    """Repo-relative paths differing from *base*, including uncommitted work.

    Committed names try ``{base}...HEAD`` first, then ``origin/{base}...HEAD``
    when *base* is an unqualified ref — CI checkouts often have the default
    branch only as a remote-tracking name. Untracked, non-ignored paths join
    the set through the shared changed-path scope.
    """
    seen: list[str] = []
    committed_specs = [f"{base}...HEAD"]
    if "/" not in str(base):
        committed_specs.append(f"origin/{base}...HEAD")
    for spec in committed_specs:
        committed = _name_only(repo_root, ["diff", "--name-only", spec])
        if committed is None:
            continue
        for line in committed:
            if line not in seen:
                seen.append(line)
        break
    names = _name_only(repo_root, ["diff", "--name-only", "HEAD"])
    for line in names or ():
        if line not in seen:
            seen.append(line)
    # Untracked work is as changed as anything else relative to the base, and
    # a newly authored file is where a fresh failure is likeliest to sit. The
    # enumeration is shared so every local mirror of a CI contract agrees on
    # what "changed" means.
    try:
        untracked = untracked_paths(repo_root)
    except ChangedPathError:
        untracked = ()
    for raw in untracked:
        line = normalize_changed_path(raw)
        if line and line not in seen:
            seen.append(line)
    return tuple(seen)


__all__ = [
    "DEFAULT_BASE_REF",
    "changed_paths",
    "normalize_changed_path",
]
