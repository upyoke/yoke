"""Collect a change-scoped selection from the full suite's own roots.

A selection named as thousands of explicit file arguments made pytest
collect each one separately, and on CI that collection outlasted the full
suite's. So a CI selection run hands pytest the project's test roots, as
full CI does, and loads this plugin (``-p``) with the selection in the file
:data:`SELECTION_FILE_ENV` names. Every directory and file outside the
selection is skipped at collection time, before its module is imported, so
collection does no more work than full CI's and usually far less.

The file holds one target per line, relative to the directory pytest starts
in (the checkout root): a test file, a directory, or a node id. A node id admits its whole file; collection never narrows
below what was selected. An unreadable or empty file is a usage error
rather than a reason to collect every root.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

#: Environment variable naming the selection file.
SELECTION_FILE_ENV = "YOKE_CI_SELECTION_FILE"

_TARGETS = pytest.StashKey["tuple[str, ...] | None"]()


def read_targets(path: Path) -> tuple[str, ...]:
    """The selected repo-relative paths, node ids reduced to their file."""
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise pytest.UsageError(
            f"ci_selection_unreadable: {SELECTION_FILE_ENV}={path} cannot be "
            f"read ({exc}); the selection run must write it before pytest starts"
        ) from exc
    targets = tuple(
        dict.fromkeys(
            line.strip().partition("::")[0].rstrip("/")
            for line in lines
            if line.strip()
        )
    )
    if not targets:
        raise pytest.UsageError(
            f"ci_selection_empty: {SELECTION_FILE_ENV}={path} names no test; "
            "an empty selection must not collect every test root"
        )
    return targets


def admits(relative: str, targets: tuple[str, ...]) -> bool:
    """Whether collection must enter *relative* to reach a selected test."""
    return any(
        relative == target
        or relative.startswith(f"{target}/")
        or target.startswith(f"{relative}/")
        for target in targets
    )


def pytest_configure(config: pytest.Config) -> None:
    named = os.environ.get(SELECTION_FILE_ENV, "").strip()
    config.stash[_TARGETS] = read_targets(Path(named)) if named else None


def pytest_ignore_collect(
    collection_path: Path, config: pytest.Config
) -> bool | None:
    targets = config.stash.get(_TARGETS, None)
    if targets is None:
        return None
    try:
        relative = collection_path.relative_to(
            config.invocation_params.dir
        ).as_posix()
    except ValueError:
        return None
    if relative == ".":
        return None
    return None if admits(relative, targets) else True


__all__ = ["SELECTION_FILE_ENV", "admits", "read_targets"]
