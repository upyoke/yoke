"""Pure inline validators for the ``yoke onboard`` wizard's free-text steps.

Each validator returns ``None`` when the value is acceptable, or a short,
user-facing error string when it is not. They are deliberately free of Textual
plumbing so they can be unit-tested directly and reused by every input step that
needs to reject bad input inline — before the wizard advances — instead of
deferring the failure to Apply.

The checks are ordered cheap -> expensive at the call site: format validators
here run first (no filesystem, no network), then the filesystem checks below, and
finally the network/auth probes the flow layer drives (URL reachability, token
publish-ability) which are not pure and live with the flow that owns that state.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

from yoke_cli.config import project_checkout_path
from yoke_cli.config import github_repository_name
from yoke_cli.config import project_git_branch

# A project slug is a lowercase, hyphen-separated identifier (e.g. ``my-project``)
# — the same shape ``slug_from_checkout`` produces and the backlog layer stores.
_SLUG_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
# An item-ID prefix is the ``PROJ`` in ``PROJ-123`` — uppercase alphanumerics,
# leading letter, a sensible 2-6 character length.
_PREFIX_RE = re.compile(r"^[A-Z][A-Z0-9]{1,5}$")
PROJECT_SLUG_MAX_LENGTH = 63


def _expand(path: str) -> Path:
    return Path(path).expanduser()


def _parent_writable(target: Path) -> bool:
    """True when ``target``'s nearest existing ancestor is a writable directory.

    A create/clone target need not exist yet, but the first existing parent up
    the chain must be a directory we can write into — otherwise the make/clone at
    apply fails. Walks up to the first ancestor that exists and tests it.
    """
    parent = target.parent
    while not parent.exists():
        if parent.parent == parent:  # reached the filesystem root
            break
        parent = parent.parent
    return parent.is_dir() and os.access(parent, os.W_OK)


def validate_clone_target_folder(path: str) -> str | None:
    """Reject a clone target that already holds files or has no writable parent.

    A clone needs a fresh, empty (or not-yet-existing) folder — git refuses to
    clone into a non-empty directory, the exact ``checkout already exists and is
    not empty`` failure this lifts to the folder step. A path that exists as a
    regular file, or one whose parent cannot be written, is rejected too.
    """
    cleaned = path.strip()
    if not cleaned:
        return "Enter a folder path."
    unsafe = project_checkout_path.validation_error(cleaned)
    if unsafe is not None:
        return unsafe
    target = _expand(cleaned)
    if target.exists():
        if not target.is_dir():
            return "That path is a file, not a folder — pick a folder path."
        try:
            non_empty = any(target.iterdir())
        except OSError:
            return "That folder can't be read — pick another path."
        if non_empty:
            return "That folder already has files — pick an empty or new path."
    if not _parent_writable(target):
        return "Yoke can't write to that location — pick a path you can write to."
    return None


def validate_clone_resume_target_folder(path: str) -> str | None:
    """Validate path safety for an exact existing clone considered for resume."""

    cleaned = path.strip()
    if not cleaned:
        return "Enter a folder path."
    unsafe = project_checkout_path.validation_error(cleaned)
    if unsafe is not None:
        return unsafe
    return validate_create_target_folder(cleaned)


def validate_create_target_folder(path: str) -> str | None:
    """Validate a create-new / existing-folder target's path shape and writability.

    An existing non-empty directory is NOT rejected here — the create-new flow
    redirects that case to adopt-the-existing-folder. A path that exists as a
    regular file (Yoke cannot make a checkout out of a plain file) or one whose
    parent cannot be written is rejected inline.
    """
    cleaned = path.strip()
    if not cleaned:
        return "Enter a folder path."
    unsafe = project_checkout_path.validation_error(cleaned)
    if unsafe is not None:
        return unsafe
    target = _expand(cleaned)
    if target.exists() and not target.is_dir():
        return "That path is a file, not a folder — pick a folder path."
    if not _parent_writable(target):
        return "Yoke can't write to that location — pick a path you can write to."
    return None


def validate_slug(value: str) -> str | None:
    """Validate a project slug: lowercase letters/digits joined by single hyphens."""
    cleaned = value.strip()
    if not cleaned:
        return "Enter a short project ID."
    if len(cleaned) > PROJECT_SLUG_MAX_LENGTH:
        return f"Use {PROJECT_SLUG_MAX_LENGTH} characters or fewer."
    if not _SLUG_RE.match(cleaned):
        return "Use lowercase letters, digits, and hyphens (e.g. my-project)."
    return None


def validate_display_name(value: str) -> str | None:
    """Validate a project display name."""
    if not value.strip():
        return "Enter a display name."
    return None


def validate_prefix(value: str) -> str | None:
    """Validate an item-ID prefix: 2-6 uppercase alphanumerics, leading letter."""
    cleaned = value.strip()
    if not cleaned:
        return "Enter an issue ID prefix."
    if not _PREFIX_RE.match(cleaned.upper()):
        return "Use 2-6 letters or digits starting with a letter (e.g. PROJ)."
    return None


def validate_branch(value: str) -> str | None:
    """Validate a branch before it can reach any Git command."""

    return project_git_branch.validation_error(value)


def validate_repository_name(value: str) -> str | None:
    """Reject names GitHub could normalize or reinterpret before a POST."""

    return github_repository_name.validation_error(value)


__all__ = [
    "PROJECT_SLUG_MAX_LENGTH",
    "validate_branch",
    "validate_clone_target_folder",
    "validate_clone_resume_target_folder",
    "validate_create_target_folder",
    "validate_display_name",
    "validate_prefix",
    "validate_repository_name",
    "validate_slug",
]
