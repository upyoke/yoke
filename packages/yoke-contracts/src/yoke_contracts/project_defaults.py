"""Which project a command targets when the caller named none.

A command standing in a checkout should target that checkout's project, not
a name compiled into the code. The machine config maps checkouts to project
ids — including worktrees, which resolve to their parent checkout — so the
directory answers the question whenever the machine knows it. The seeded
slug is the last resort for a runner standing nowhere in particular.
"""

from __future__ import annotations

from pathlib import Path

from yoke_contracts.machine_config.runtime import project_id

#: Slug the installer seeds for the project that owns a Yoke installation.
#: A compatibility fact, not an authority: code that must know *which*
#: project is the self project reads the checkout binding instead.
DEFAULT_PROJECT_SLUG = "yoke"


def default_project_for_directory(directory: str | Path) -> str:
    """The project *directory* belongs to, or the seeded slug.

    Returns the project id as a string when the machine config binds the
    directory (or one of its ancestors) to a project — every
    project-accepting surface resolves ids and slugs alike.
    """
    try:
        resolved = project_id(Path(directory))
    except Exception:  # noqa: BLE001 - an unreadable config is not fatal
        resolved = None
    return DEFAULT_PROJECT_SLUG if resolved is None else str(resolved)


__all__ = ["DEFAULT_PROJECT_SLUG", "default_project_for_directory"]
