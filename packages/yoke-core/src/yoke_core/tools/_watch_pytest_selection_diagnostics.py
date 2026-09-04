"""Selection diagnostics for the pytest watcher's explicit file arguments.

Split from :mod:`yoke_core.tools._watch_pytest_args` to keep that module
under the authored-file line cap. These functions explain a pass-through
that names test files pytest cannot use — a missing path, or a selection
that collected nothing — before or after the run, so the capture says why
nothing ran instead of ending in silence.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Sequence


# Pytest flags that consume the following token, so a flag value like
# ``-k runtime`` is never mistaken for a positional path arg.
_PYTEST_VALUE_FLAGS = frozenset(
    {"-k", "-m", "-n", "-p", "-o", "-W", "-c", "--rootdir", "--numprocesses"}
)


def pytest_flag_consumes_value(token: str) -> bool:
    """Whether *token* is a pytest flag whose value is the next token."""
    return token in _PYTEST_VALUE_FLAGS


def has_bare_runtime_path(args: Sequence[str]) -> bool:
    """Return True when a positional pytest path arg is bare ``runtime``.

    Covers the ``runtime``, ``runtime/``, and ``./runtime/`` spellings
    via normpath. Anchored paths (``runtime/api/``) and flag values are
    never matched.
    """
    skip_next = False
    for token in args:
        if skip_next:
            skip_next = False
            continue
        if token.startswith("-"):
            skip_next = token in _PYTEST_VALUE_FLAGS
            continue
        if os.path.normpath(token) == "runtime":
            return True
    return False


def supplied_test_files(args: Sequence[str]) -> tuple[str, ...]:
    """Return explicit ``.py`` collection paths in pass-through *args*.

    Pytest node ids retain their selector suffix for the diagnostic while
    path validation below checks only the file portion before ``::``.
    """
    files: list[str] = []
    skip_next = False
    for token in args:
        if skip_next:
            skip_next = False
            continue
        if token == "--":
            continue
        if token.startswith("-"):
            skip_next = token in _PYTEST_VALUE_FLAGS
            continue
        if token.partition("::")[0].endswith(".py") and token not in files:
            files.append(token)
    return tuple(files)


def _missing_test_files(args: Sequence[str], cwd: Path) -> tuple[str, ...]:
    return tuple(
        token
        for token in supplied_test_files(args)
        if not (cwd / token.partition("::")[0]).is_file()
    )


def invalid_test_selection_diagnostic(args: Sequence[str], cwd: Path) -> str | None:
    """Explain a mixed explicit-file selection containing missing paths."""
    files = supplied_test_files(args)
    missing = set(_missing_test_files(args, cwd))
    if not missing:
        return None
    lines = [
        "watch_pytest invalid selection: "
        f"{len(files)} supplied test file(s), {len(missing)} missing; "
        "pytest was not started."
    ]
    for token in files:
        reason = (
            "path does not exist"
            if token in missing
            else "exists; not run because the combined selection is invalid"
        )
        lines.append(f"watch_pytest selection: {token} — {reason}")
    return "\n".join(lines)


def _active_selection_filters(args: Sequence[str]) -> tuple[str, ...]:
    filters: list[str] = []
    for index, token in enumerate(args):
        if token in {"-k", "-m"} and index + 1 < len(args):
            filters.append(f"{token} {args[index + 1]}")
        elif token.startswith(("-k", "-m")) and not token.startswith("--"):
            filters.append(token)
    return tuple(filters)


def zero_collection_diagnostic(
    args: Sequence[str], collected_items: int | None, cwd: Path
) -> str | None:
    """Explain an all-existing explicit selection that yielded no items."""
    files = supplied_test_files(args)
    if collected_items != 0 or not files:
        return None
    missing = set(_missing_test_files(args, cwd))
    filters = _active_selection_filters(args)
    lines = [
        f"# watch_pytest zero-collection selection: {len(files)} supplied test file(s)"
    ]
    for token in files:
        if token in missing:
            reason = "path does not exist"
        elif missing:
            reason = "not collected after pytest received a missing path"
        elif filters:
            reason = "no item matched active filter(s): " + ", ".join(filters)
        else:
            reason = "pytest reported no collectable items in this selection"
        lines.append(f"# watch_pytest no-items: {token} — {reason}")
    return "\n".join(lines)


__all__ = [
    "has_bare_runtime_path",
    "invalid_test_selection_diagnostic",
    "pytest_flag_consumes_value",
    "supplied_test_files",
    "zero_collection_diagnostic",
]
