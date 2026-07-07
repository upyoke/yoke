"""Compatibility wrapper for default file-line exception globs."""

from __future__ import annotations

from yoke_contracts.project_contract.file_line_policy import (
    DEFAULT_EXCEPTION_GLOBS,
    default_exception_globs,
)


def temporary_exceptions() -> tuple[str, ...]:
    """Return built-in exception globs before project-local policy is added."""
    return default_exception_globs()


__all__ = (
    "DEFAULT_EXCEPTION_GLOBS",
    "temporary_exceptions",
)
