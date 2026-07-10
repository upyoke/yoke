"""Run the merge engine with transient local GitHub App test authorization."""

from __future__ import annotations

from yoke_core.domain.project_github_auth import (
    bind_local_github_user_token_provider,
)
from yoke_core.engines.merge_worktree import main


def run() -> int:
    with bind_local_github_user_token_provider(
        lambda: "transient-test-user-token",
        api_url="https://api.github.com",
    ):
        return main()


if __name__ == "__main__":
    raise SystemExit(run())
