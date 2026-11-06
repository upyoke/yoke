"""Runtime interface for repo upstream freshness."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Protocol, cast

from yoke_contracts.runtime_ports.loader import load_port


class RepoUpstreamFreshness(Protocol):
    """Operations and values supplied by the executing adapter."""

    UpstreamFreshness: type[Any]
    refresh_base_branch: Callable[..., Any]


def get_repo_upstream_freshness() -> RepoUpstreamFreshness:
    return cast(RepoUpstreamFreshness, load_port("repo_upstream_freshness", RepoUpstreamFreshness))
