"""Register repository GitHub operations, including installer proposals."""

from __future__ import annotations

from yoke_core.domain.handlers import github_pr_create
from yoke_core.domain.handlers import github_branch_head
from yoke_core.domain.handlers import github_commit_release_tag
from yoke_core.domain.handlers import github_merge_queue_apply
from yoke_core.domain.handlers import github_merge_queue_hold
from yoke_core.domain.handlers import github_merge_queue_readiness
from yoke_core.domain.handlers import github_open_work


def register(registry) -> None:
    """Register the github family handlers via the given registry."""
    for entry in (
        *github_pr_create.REGISTRATIONS,
        *github_commit_release_tag.REGISTRATIONS,
        *github_branch_head.REGISTRATIONS,
        *github_merge_queue_apply.REGISTRATIONS,
        *github_merge_queue_hold.REGISTRATIONS,
        *github_merge_queue_readiness.REGISTRATIONS,
        *github_open_work.REGISTRATIONS,
    ):
        registry.register(**entry)
