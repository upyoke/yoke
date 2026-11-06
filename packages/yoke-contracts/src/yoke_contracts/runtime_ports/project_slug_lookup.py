"""Runtime interface for project slug lookup."""

from __future__ import annotations

from typing import Any, Protocol, cast

from yoke_contracts.runtime_ports.loader import load_port


class ProjectSlugLookup(Protocol):
    """Operations and values supplied by the executing adapter."""

    ProjectSlugLookupError: type[Any]


def get_project_slug_lookup() -> ProjectSlugLookup:
    return cast(ProjectSlugLookup, load_port("project_slug_lookup", ProjectSlugLookup))
