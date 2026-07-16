"""Handler registrations for the repo-level ``github.*`` family.

Distinct from ``_register_github_actions``: PRs are repo-level GitHub
surfaces, not Actions surfaces. Carries ``github.pr.create`` so agents
open pull requests through the bearer-token REST transport with no host
GitHub CLI binary.
"""
from __future__ import annotations

from yoke_core.domain.handlers import github_pr_create, github_release_tag


def register(registry) -> None:
    """Register the github family handlers via the given registry."""
    for entry in (*github_pr_create.REGISTRATIONS, *github_release_tag.REGISTRATIONS):
        registry.register(**entry)
