"""Verify ownership of a prior runtime's GitHub credential launcher."""

from __future__ import annotations

import os
import stat
from pathlib import Path

from yoke_cli.config import github_git_credential_launcher

RELEASES_ROOT_NAME = "yoke-cli-releases"


def current_release_path(path: Path) -> Path:
    """Map a path inside a release generation onto the ``current`` alias."""
    generation = _release_generation(path)
    if generation is None:
        return path
    return generation.parent.parent / "current" / path.relative_to(generation)


def orphaned_release_helper(
    python: str,
    helper: str,
    *,
    current_python: Path,
) -> bool:
    """Recognize a release helper a Python minor-version change left behind.

    A release switch that changes the Python minor version moves the old
    ``lib/python3.X/site-packages`` helper out from under the saved command.
    The command is still Yoke's when both paths name this machine's releases
    root on their literal text and the helper file is gone. Editable and
    source installs have no releases root, so they never match.
    """
    generation = _release_generation(current_python)
    if generation is None:
        return False
    root = generation.parent.parent
    paths = (Path(python), Path(helper))
    return (
        not any(".." in path.parts for path in paths)
        and all(path.is_relative_to(root) for path in paths)
        and not paths[1].exists()
    )


def _release_generation(path: Path) -> Path | None:
    for generation in path.parents:
        releases = generation.parent
        if releases.name == "releases" and releases.parent.name == RELEASES_ROOT_NAME:
            return generation
    return None


def verified_prior_runtime_helper(
    python: Path,
    helper: Path,
    *,
    current_python: Path,
) -> bool:
    """Recognize a safe prior-runtime launcher without trusting its path."""

    try:
        python_info = python.stat()
        if not stat.S_ISREG(python_info.st_mode) or not os.access(python, os.X_OK):
            return False
        if python != current_python and stat.S_IMODE(python_info.st_mode) & 0o022:
            return False
        flags = (
            os.O_RDONLY
            | getattr(os, "O_NOFOLLOW", 0)
            | getattr(
                os,
                "O_NONBLOCK",
                0,
            )
        )
        descriptor = os.open(helper, flags)
    except OSError:
        return False
    try:
        info = os.fstat(descriptor)
        if (
            not stat.S_ISREG(info.st_mode)
            or stat.S_IMODE(info.st_mode) & 0o022
            or info.st_size > 256 * 1024
        ):
            return False
        source = os.read(descriptor, 256 * 1024 + 1)
    except OSError:
        return False
    finally:
        os.close(descriptor)
    if not all(
        marker in source
        for marker in (
            b'BUNDLE_POINTER_NAME = "_yoke_github_helper_current"',
            b'BUNDLE_HELPER_NAME = "_yoke_github_git_credential_helper.py"',
            b"def selected_bundle(",
        )
    ):
        return False
    try:
        # The stable launcher is meaningful only beside a content-addressed,
        # integrity-checked bundle.  Marker-shaped files on their own remain
        # user-managed lookalikes and must never be removed automatically.
        github_git_credential_launcher.selected_bundle(
            helper.parent,
            module_names=github_git_credential_launcher.prior_launcher_module_names(
                source
            ),
        )
    except (OSError, github_git_credential_launcher.GitHubCredentialLauncherError):
        return False
    return True
