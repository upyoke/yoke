"""The person a new universe's first administrator is named for.

``yoke setup`` asks the installer's name and births the universe's first
human actor as that person. A self-host bundle carries the answer in its
``.env`` as :data:`ADMIN_NAME_ENV`, which the server's first boot reads; a
local universe receives it directly. One validator serves every entry
point, so a name the wizard accepts is a name the bundle can carry: Docker
Compose interpolates ``$`` and strips quotes and comments inside ``.env``
values, so those characters are refused rather than silently rewritten.
"""

from __future__ import annotations

#: Bundle ``.env`` key naming the first administrator for server first boot.
ADMIN_NAME_ENV = "YOKE_ADMIN_NAME"

#: Named refusal when a server birth has no first-administrator name.
ADMIN_NAME_MISSING = "first_admin_name_missing"

MAX_ADMIN_NAME_LENGTH = 100
_ENV_UNSAFE_CHARACTERS = frozenset("$#\"'`\\")


class AdminNameError(ValueError):
    """The offered name cannot name the first administrator."""


def validate_admin_name(value: object) -> str:
    """Return the cleaned name, or raise :class:`AdminNameError` saying why."""
    name = str(value or "").strip()
    if not name:
        raise AdminNameError(
            "your name is required: it names this universe's first admin"
        )
    if len(name) > MAX_ADMIN_NAME_LENGTH:
        raise AdminNameError(
            f"use at most {MAX_ADMIN_NAME_LENGTH} characters for your name"
        )
    if any(not char.isprintable() for char in name):
        raise AdminNameError("your name cannot contain control characters")
    unsafe = sorted({char for char in name if char in _ENV_UNSAFE_CHARACTERS})
    if unsafe:
        raise AdminNameError(
            "your name cannot contain "
            + " ".join(unsafe)
            + " (the server bundle's .env cannot carry them literally)"
        )
    return name


__all__ = [
    "ADMIN_NAME_ENV",
    "ADMIN_NAME_MISSING",
    "AdminNameError",
    "MAX_ADMIN_NAME_LENGTH",
    "validate_admin_name",
]
