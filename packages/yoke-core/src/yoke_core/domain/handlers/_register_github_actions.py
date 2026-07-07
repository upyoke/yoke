"""Handler registrations for ``github_actions.*`` handlers.

Agent-facing PAT-backed GitHub Actions surfaces. Carries
``github_actions.check_ci`` (main-branch CI advisory) plus the repo
config writers ``github_actions.secret.set`` (sealed-box repo secret)
and ``github_actions.variable.set`` (repo variable upsert) plus the
read-only ``github_actions.variable.get`` arming-gate probe, so the
usher pre-merge / post-merge recipe and the CI arming / rotation
recipes all run on a laptop with no host GitHub CLI binary.
"""
from __future__ import annotations

from yoke_core.domain.handlers import (
    github_actions_check_ci,
    github_actions_get,
    github_actions_runners,
    github_actions_run,
    github_actions_set,
)


def register(registry) -> None:
    """Register the github_actions family handlers via the given registry."""
    for entry in (
        *github_actions_check_ci.REGISTRATIONS,
        *github_actions_get.REGISTRATIONS,
        *github_actions_runners.REGISTRATIONS,
        *github_actions_run.REGISTRATIONS,
        *github_actions_set.REGISTRATIONS,
    ):
        registry.register(**entry)
