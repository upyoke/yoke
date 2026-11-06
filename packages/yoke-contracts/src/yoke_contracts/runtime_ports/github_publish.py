"""Runtime interface for github publish."""

from __future__ import annotations

from typing import Any, Protocol, cast

from yoke_contracts.runtime_ports.loader import load_port


class GithubPublish(Protocol):
    """Operations and values supplied by the executing adapter."""

    GitHubPublishError: Any


def get_github_publish() -> GithubPublish:
    return cast(GithubPublish, load_port("github_publish", GithubPublish))
