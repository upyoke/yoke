"""Existing-project reuse state and presentation for onboarding."""

from __future__ import annotations

from typing import Any

from yoke_cli.config import existing_project_lookup
from yoke_cli.config.onboard_destinations import DESTINATION_LOCAL
from yoke_cli.config.project_github_adoption import GITHUB_ADOPTION_BACKLOG_ONLY


def match_summary(result: Any) -> str:
    """Summarize how the current checkout matched an existing project."""
    source = getattr(result, "existing_project_match_source", None)
    database = _database_label(result)
    if source == existing_project_lookup.MATCH_SOURCE_LOCAL_CHECKOUT:
        return f"Local project metadata matched a {database} project."
    if source == existing_project_lookup.MATCH_SOURCE_GITHUB_REPO:
        return f"The {database} already has a project for this GitHub repo."
    return "Yoke found an existing project and will reuse it."


def match_lines(result: Any) -> list[str]:
    """Build verification details for an existing-project match."""
    source = getattr(result, "existing_project_match_source", None)
    project_id = getattr(result, "existing_project_id", None)
    github_repo = str(getattr(result, "project_github_repo", "") or "").strip()
    local_source = str(
        getattr(result, "existing_project_local_source", "") or ""
    ).strip()
    database = _database_label(result)

    if source == existing_project_lookup.MATCH_SOURCE_LOCAL_CHECKOUT:
        local_label = local_source or "local checkout metadata"
        return [
            f"Local machine: found project id {project_id} in {local_label}.",
            f"{database}: verified project id {project_id}.",
        ]
    if source == existing_project_lookup.MATCH_SOURCE_GITHUB_REPO:
        repo_label = f"GitHub repo {github_repo}" if github_repo else "the GitHub repo"
        return [
            f"{database}: matched {repo_label}.",
            "Local machine: no existing Yoke project metadata was used.",
        ]
    return [f"{database}: existing project verified."]


def record_match(
    result: Any,
    project: existing_project_lookup.ExistingProject,
    *,
    match_source: str | None = None,
    local_source: str | None = None,
) -> None:
    """Record an existing project and clear creation-only wizard state."""
    result.existing_project_id = project.id
    result.existing_project_match_source = match_source
    result.existing_project_local_source = local_source
    result.project_slug = project.slug
    result.project_name = project.name
    result.project_github_repo = project.github_repo
    result.project_default_branch = project.default_branch
    result.project_public_item_prefix = project.public_item_prefix
    result.project_github_adoption = GITHUB_ADOPTION_BACKLOG_ONLY
    result.project_publish_to_github = False
    result.project_publish_owner = None
    result.project_publish_repo_name = None
    result.board_art_word = None
    result.board_art_seed = None
    result.board_art_variants = []


def lookup_error_hint(*, local_destination: bool) -> str:
    """Explain how to recover from a failed existing-project lookup."""
    if local_destination:
        return (
            "Verify this machine's local universe, or choose a different project "
            "option."
        )
    return (
        "Use a Yoke API token that can access this project, or choose "
        "a different project option."
    )


def _database_label(result: Any) -> str:
    return (
        "local Yoke database"
        if getattr(result, "destination", None) == DESTINATION_LOCAL
        else "Yoke core database"
    )


__all__ = ["lookup_error_hint", "match_lines", "match_summary", "record_match"]
