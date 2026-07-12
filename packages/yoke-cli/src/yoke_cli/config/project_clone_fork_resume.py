"""Detect a fork created by a prior partially completed clone flow."""

from __future__ import annotations

from pathlib import Path

from yoke_contracts import github_origin
from yoke_cli.config import project_clone_resume


def existing_fork_repo(
    root: Path,
    *,
    remote_url: str,
    web_url: str,
) -> str | None:
    """Return a prior run's fork when origin changed and upstream is source."""

    origin = project_clone_resume.remote_url(root, "origin")
    upstream = project_clone_resume.remote_url(root, "upstream")
    if not (origin and upstream and project_clone_resume.same_repo(
        upstream, remote_url, web_url=web_url,
    )):
        return None
    try:
        fork_repo = github_origin.normalize_github_repository(
            origin, web_url=web_url,
        )
        source_repo = github_origin.normalize_github_repository(
            remote_url, web_url=web_url,
        )
    except github_origin.GitHubApiOriginError:
        return None
    return fork_repo if fork_repo.casefold() != source_repo.casefold() else None


__all__ = ["existing_fork_repo"]
