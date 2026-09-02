"""Project-form reset and default-value helpers for onboarding."""

from __future__ import annotations

from typing import Any

PREFIX_PROMPT_TITLE = "Pick the issue ID prefix."
PREFIX_PROMPT_SUBTITLE = (
    "The PROJ in PROJ-123 — choose a unique prefix; "
    "Yoke does not suggest or derive one."
)


def reset_project_fields(result: Any) -> None:
    """Clear project fields when the user changes onboarding direction."""
    result.project_remote_url = None
    result.project_checkout = None
    result.project_slug = None
    result.project_name = None
    result.project_github_repo = None
    result.project_github_repository_id = None
    result.project_github_installation_id = None
    result.project_checkout_origin_url = None
    result.project_checkout_github_repo = None
    result.project_default_branch = None
    result.project_public_item_prefix = None
    result.existing_project_id = None
    result.existing_project_match_source = None
    result.existing_project_local_source = None
    result.project_github_adoption = None
    result.project_github_adoption_preserve = False
    reset_project_publish_fields(result)
    result.project_clone_outcome = None
    result.project_clone_existing_layer_decision = ""
    result.project_clone_keep_upstream = True
    result.project_clone_requires_machine_github = False
    result.project_source_default_branch = None
    result.project_keep_existing_remote = False
    result.board_art_word = None
    result.board_art_seed = None
    result.board_art_variants = []


def reset_project_publish_fields(result: Any) -> None:
    """Clear every create/manual-attach field as one navigation transaction."""
    result.project_publish_to_github = False
    result.project_publish_owner = None
    result.project_publish_owner_login = None
    result.project_publish_repo_name = None
    result.project_publish_private = True
    result.project_publish_create_repository = True
    result.project_publish_repository_id = None
    result.project_publish_installation_id = None


def slug_from_checkout(checkout: str | None) -> str:
    """Derive a safe default project slug from a checkout path."""
    if not checkout:
        return "project"
    value = checkout.rstrip("/").split("/")[-1].strip().lower()
    cleaned = "".join(c if c.isalnum() or c == "-" else "-" for c in value)
    return "-".join(part for part in cleaned.split("-") if part) or "project"


def prefix_from_slug(slug: str | None) -> str:
    """The public-item prefix is an explicit setting, never derived from a slug."""
    del slug
    return ""
