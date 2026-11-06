"""Runtime interface for repo upstream git."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Protocol, cast

from yoke_contracts.runtime_ports.loader import load_port


class RepoUpstreamGit(Protocol):
    """Operations and values supplied by the executing adapter."""

    NETWORK_TIMEOUT_SETTING_KEY: Any
    READ_TIMEOUT_SECONDS: Any
    branch_checkout_path: Callable[..., Any]
    count_ahead_behind: Callable[..., Any]
    fast_forward: Callable[..., Any]
    fetch_branch: Callable[..., Any]
    git: Callable[..., Any]
    network_timeout_seconds: Callable[..., Any]
    out: Callable[..., Any]
    reason: Callable[..., Any]
    resolve_base_branch: Callable[..., Any]
    resolve_remote: Callable[..., Any]
    tracking_ref: Callable[..., Any]


def get_repo_upstream_git() -> RepoUpstreamGit:
    return cast(RepoUpstreamGit, load_port("repo_upstream_git", RepoUpstreamGit))
