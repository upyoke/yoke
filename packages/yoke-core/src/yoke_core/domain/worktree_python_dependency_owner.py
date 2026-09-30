"""Who owns a lane's Python dependencies: uv, or installation conventions.

Convention detection (``requirements.txt``, ``Pipfile.lock``, and their
nested variants) assumes nothing else installs the lane's Python packages.
A uv-managed project breaks that assumption: its environment comes from its
own lockfile, materialized by lane test-environment provisioning.

Asking the question here keeps one answer for both sides. Running both
owners installed a second, unpinned dependency set beside the pinned one —
on a repository whose nested ``requirements.txt`` predated its uv migration,
that meant building pinned wheels from source on every single preparation,
and failing outright wherever a pinned build did not support the lane's
interpreter version.
"""

from __future__ import annotations

from pathlib import Path

from yoke_contracts.uv_project import (
    LOCKFILE_NAME,
    PROJECT_FILE_NAME,
    UV_EXECUTABLE,
)


def uv_provisioned_projects(worktree_path: str) -> tuple[str, ...]:
    """Lane-relative labels of every uv-managed project in *worktree_path*.

    A non-empty answer means uv owns the lane's Python environment, so
    convention detection must leave that axis alone. The discovery is the
    same walk lane test-environment provisioning uses, so the two surfaces
    cannot disagree about which projects it will sync.
    """
    from yoke_core.domain.worktree_test_environment import uv_projects

    root = Path(worktree_path)
    try:
        return tuple(
            "." if project == root else str(project.relative_to(root))
            for project in uv_projects(root)
        )
    except OSError:
        # An unscannable tree is not a uv claim on the Python axis; the
        # convention detectors still get their chance.
        return ()


def uv_provisioned_skip_note(label: str) -> str:
    """The line a lane prints instead of installing Python by convention."""
    return (
        f"Skipping convention Python install for {label}: it is uv-managed "
        f"({PROJECT_FILE_NAME} beside {LOCKFILE_NAME}), so lane "
        f"test-environment provisioning installs it with "
        f"`{UV_EXECUTABLE} sync`."
    )


__all__ = ["uv_provisioned_projects", "uv_provisioned_skip_note"]
