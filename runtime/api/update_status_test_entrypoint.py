"""Subprocess entrypoint binding deterministic local GitHub App user auth."""

from __future__ import annotations

from yoke_core.domain.project_github_auth import (
    bind_local_github_user_token_provider,
)
from yoke_core.domain.update_status import main


if __name__ == "__main__":
    with bind_local_github_user_token_provider(
        lambda: "ghu_update_status_test",
        api_url="https://api.github.com",
    ):
        raise SystemExit(main())
