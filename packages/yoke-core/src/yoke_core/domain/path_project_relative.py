"""Validation for project-relative path strings."""

from __future__ import annotations

from typing import Iterable, List

from yoke_contracts.path_snapshot import (
    invalid_project_relative_paths as _invalid_project_relative_paths,
)


def invalid_project_relative_paths(paths: Iterable[str]) -> List[str]:
    """Return paths that cannot name a repo-relative path target."""
    return _invalid_project_relative_paths(paths)


__all__ = ["invalid_project_relative_paths"]
