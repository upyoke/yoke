"""Directory walks for doctor checks that scan a live working tree.

A doctor scan reads a tree other processes are rewriting: parallel test shards
build wheels under ``build/``, worktrees appear and vanish, ``__pycache__`` and
virtualenv directories churn. ``pathlib`` recursive globbing lets the resulting
``FileNotFoundError`` escape from the middle of the walk — before 3.13 only
``PermissionError`` is absorbed — and a generator cannot be resumed once it has
raised. So a check either dies on a directory it never cared about, or, if it
catches the error around its loop, abandons the rest of the tree and reports
what it managed to read. The second shape is the dangerous one: a partial walk
that finds nothing is indistinguishable from a clean tree.

``os.walk`` hands directory errors to a handler and keeps going, so every scan
here walks with it — the directory that vanished is skipped and the rest of the
tree is still read. Only ``FileNotFoundError`` is absorbed: a permission fault
is a real fact about the tree rather than a race, and still stops the scan.
"""

from __future__ import annotations

import os
from fnmatch import fnmatchcase
from pathlib import Path
from typing import Collection, Iterator, List

#: Python trees a build writes. They mirror package source, and packaging
#: rewrites them underneath a running scan, so no scan wants to enter them.
GENERATED_TREE_NAMES = frozenset({"build", "dist"})


def _tolerate_removed_directory(error: OSError) -> None:
    if not isinstance(error, FileNotFoundError):
        raise error


def iter_tree_files(
    base: Path,
    pattern: str = "*",
    *,
    prune_dir_names: Collection[str] = (),
) -> Iterator[Path]:
    """Yield files under *base* whose name matches *pattern*.

    Directories named in *prune_dir_names* are never descended into. Anything
    removed while the walk runs is skipped instead of ending the scan.
    """
    for directory, dirnames, filenames in os.walk(
        base, onerror=_tolerate_removed_directory
    ):
        dirnames[:] = sorted(name for name in dirnames if name not in prune_dir_names)
        for filename in sorted(filenames):
            if fnmatchcase(filename, pattern):
                yield Path(directory) / filename


def list_directory(base: Path) -> List[Path]:
    """Return *base*'s children sorted, or nothing when *base* has vanished."""
    try:
        return sorted(base.iterdir())
    except FileNotFoundError:
        return []


__all__ = ["GENERATED_TREE_NAMES", "iter_tree_files", "list_directory"]
