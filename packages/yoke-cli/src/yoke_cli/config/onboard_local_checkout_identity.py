"""GitHub origin and branch identity for an existing local checkout."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from yoke_cli.config import existing_project_lookup
from yoke_cli.config import onboard_wizard_github_state as github_state
from yoke_cli.config import project_clone_resume
from yoke_cli.config import project_git_transport
from yoke_cli.config.project_publish_support import is_git_repo


def inspect(result: Any, value: str) -> tuple[str | None, str | None]:
    """Record current branch/GitHub repo and return raw remote + web origin."""

    checkout = Path(value).expanduser()
    inside_git_checkout = is_git_repo(checkout)
    exact_git_root = (
        inside_git_checkout
        and project_clone_resume.is_exact_worktree_root(checkout)
    )
    if inside_git_checkout and not exact_git_root:
        raise RuntimeError(
            "Select the exact Git worktree root, not a nested folder inside it."
        )
    branch = project_git_transport.git_current_branch(
        checkout
    ) if exact_git_root else None
    remote = project_clone_resume.remote_url(
        checkout, "origin",
    ) if exact_git_root else None
    web_url = github_state.clone_web_url(result) if remote else None
    repository = (
        existing_project_lookup.normalize_github_repo(
            remote, web_url=web_url,
        )
        if remote else ""
    )
    result.project_source_default_branch = branch
    result.project_checkout_origin_url = remote
    result.project_checkout_github_repo = repository or None
    result.project_github_repo = repository or None
    return remote, web_url


def require_matching_origin(
    checkout: str | Path,
    *,
    github_repo: str,
    web_url: str,
) -> None:
    """Require the checkout's live origin to be the intended GitHub repository."""

    selected = Path(checkout).expanduser()
    remote = (
        project_clone_resume.remote_url(selected, "origin")
        if project_clone_resume.is_exact_worktree_root(selected)
        else None
    )
    repository = existing_project_lookup.normalize_github_repo(
        remote, web_url=web_url,
    ) if remote else ""
    if not remote or repository.casefold() != github_repo.casefold():
        actual = repository or ("an unrecognized origin" if remote else "no origin")
        raise RuntimeError(
            "This checkout's live origin does not match the saved GitHub "
            f"repository ({actual} != {github_repo}). Choose a different checkout "
            "or repair origin before continuing."
        )


__all__ = ["inspect", "require_matching_origin"]
