"""What makes a directory a uv-managed Python project, and how to run in it.

A directory qualifies when it holds both a ``pyproject.toml`` and a
``uv.lock`` — the pair that makes ``uv run --frozen`` deterministic. Two
surfaces depend on the same answer: the ``yoke watch`` adapters, which
re-exec a wrapper inside the surrounding project's environment, and lane
preparation, which materializes that environment before calling a
worktree ready. They agree because the predicate lives here rather than
once per caller.
"""

from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Mapping, Optional, Sequence

UV_EXECUTABLE = "uv"
PROJECT_FILE_NAME = "pyproject.toml"
LOCKFILE_NAME = "uv.lock"

#: Variables that point uv at an environment other than the project's own.
#: A caller already inside another checkout's environment carries them, and
#: a ``uv sync`` or ``uv run`` that inherited them would install the
#: discovered project's lock into that other environment.
FOREIGN_ENVIRONMENT_VARIABLES = ("UV_PROJECT_ENVIRONMENT", "VIRTUAL_ENV")


def is_uv_project(directory: Path) -> bool:
    """True when *directory* holds both the project file and the lockfile."""
    return (directory / PROJECT_FILE_NAME).is_file() and (
        directory / LOCKFILE_NAME
    ).is_file()


def uv_project_root(start: Path) -> Optional[Path]:
    """Return the nearest ancestor of *start* that is a uv-managed project.

    Returns ``None`` when no ancestor qualifies, which is the signal to a
    caller that there is no project environment to bind.
    """
    try:
        here = start.resolve()
    except OSError:
        return None
    for candidate in [here, *here.parents]:
        if is_uv_project(candidate):
            return candidate
    return None


def uv_run_argv(trailing: Sequence[str]) -> List[str]:
    """The ``uv run --frozen python3 …`` argv for *trailing*.

    ``--frozen`` runs the environment the lockfile describes and never
    re-locks, so a run cannot silently drift from what the project pinned.
    """
    return [UV_EXECUTABLE, "run", "--frozen", "python3", *trailing]


def project_own_environment(env: Mapping[str, str]) -> Dict[str, str]:
    """A copy of *env* under which uv uses the discovered project's ``.venv``."""
    return {
        key: value
        for key, value in env.items()
        if key not in FOREIGN_ENVIRONMENT_VARIABLES
    }


__all__ = [
    "FOREIGN_ENVIRONMENT_VARIABLES",
    "LOCKFILE_NAME",
    "PROJECT_FILE_NAME",
    "UV_EXECUTABLE",
    "is_uv_project",
    "project_own_environment",
    "uv_project_root",
    "uv_run_argv",
]
