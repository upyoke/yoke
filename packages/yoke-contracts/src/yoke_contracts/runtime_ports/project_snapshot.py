"""Runtime interface for project snapshot."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Protocol, cast

from yoke_contracts.runtime_ports.loader import load_port


class ProjectSnapshot(Protocol):
    """Operations and values supplied by the executing adapter."""

    sync_local_snapshot_for_write: Callable[..., Any]


def get_project_snapshot() -> ProjectSnapshot:
    return cast(ProjectSnapshot, load_port("project_snapshot", ProjectSnapshot))
