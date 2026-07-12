"""Pure branch-name validation shared by GitHub metadata and Git commands."""

from __future__ import annotations

import unicodedata


MAX_BRANCH_NAME_CHARS = 255
_FORBIDDEN = frozenset("~^:?*[\\")


def branch_validation_error(value: str) -> str | None:
    if not value:
        return "Enter a branch name."
    if value != value.strip():
        return "A branch name can't have leading or trailing spaces."
    if len(value) > MAX_BRANCH_NAME_CHARS:
        return f"Use {MAX_BRANCH_NAME_CHARS} characters or fewer."
    if value.startswith("-"):
        return "A branch name can't start with a hyphen."
    if value == "@":
        return "That branch name is reserved — pick another."
    if any(
        ord(char) <= 32
        or ord(char) == 127
        or unicodedata.category(char) in {"Cc", "Cf"}
        for char in value
    ):
        return "A branch name can't contain spaces or control characters."
    components = value.split("/")
    if (
        any(not component or component.startswith(".") for component in components)
        or any(component.endswith((".", ".lock")) for component in components)
        or ".." in value
        or "@{" in value
        or any(char in _FORBIDDEN for char in value)
    ):
        return "That isn't a valid branch name — use letters, digits, - / _ . "
    return None


def is_valid_branch(value: str) -> bool:
    return branch_validation_error(value) is None


__all__ = [
    "MAX_BRANCH_NAME_CHARS", "branch_validation_error", "is_valid_branch",
]
