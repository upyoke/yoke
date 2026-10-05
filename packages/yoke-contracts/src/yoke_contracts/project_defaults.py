"""Which project a command targets when the caller named none.

A command standing in a checkout should target that checkout's project, not
a name compiled into the code. The machine config maps checkouts to project
ids — including worktrees, which resolve to their parent checkout — so the
directory answers the question whenever the machine knows it. An unmapped
directory has no project; callers must refuse or report not applicable.
"""

from __future__ import annotations

from pathlib import Path

from yoke_contracts.machine_config.runtime import project_id


def default_project_for_directory(directory: str | Path) -> str | None:
    """The project *directory* belongs to, or ``None``.

    Returns the project id as a string when the machine config binds the
    directory (or one of its ancestors) to a project — every
    project-accepting surface resolves ids and slugs alike.
    """
    try:
        resolved = project_id(Path(directory))
    except Exception:  # noqa: BLE001 - an unreadable config is not fatal
        resolved = None
    return None if resolved is None else str(resolved)


class MissingProjectError(ValueError):
    """A project-scoped operation has no caller-selected project."""


def missing_project_message(projects: list[str], *, unavailable: str = "") -> str:
    """Explain the refusal using only the caller's accessible roster."""
    roster = ", ".join(projects) if projects else "none"
    if unavailable:
        roster = f"unavailable ({unavailable}); check `yoke env list` and retry"
    return f"project_required: no project given — pass --project P. Accessible projects: {roster}."


__all__ = [
    "MissingProjectError",
    "default_project_for_directory",
    "missing_project_message",
]
