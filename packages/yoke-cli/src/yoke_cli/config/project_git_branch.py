"""User-facing wrapper for the shared exact branch-name contract."""

from __future__ import annotations

from yoke_contracts import git_ref_name


MAX_BRANCH_NAME_CHARS = git_ref_name.MAX_BRANCH_NAME_CHARS


def validation_error(value: str) -> str | None:
    """Return one user-facing reason when ``value`` is not a safe branch."""

    return git_ref_name.branch_validation_error(value)


def is_valid(value: str) -> bool:
    return git_ref_name.is_valid_branch(value)


__all__ = ["MAX_BRANCH_NAME_CHARS", "is_valid", "validation_error"]
