"""Offer text for the registered git-bootstrap operation.

One recipe, reused wherever a missing git remote currently bites, so
repair hints and packet teaching name the same command.
"""

from __future__ import annotations

GIT_BOOTSTRAP_USAGE = (
    "yoke project git bootstrap CHECKOUT [--no-init] [--no-create-remote] "
    "[--project SLUG] [--owner OWNER] [--name NAME] [--default-branch BRANCH] "
    "[--config PATH] [--yes | --dry-run] [--session-id S] [--json]"
)

GIT_BOOTSTRAP_OFFER = (
    "run `yoke project git bootstrap CHECKOUT --project {project} --yes` "
    "to init the checkout, create a private GitHub repository, and bind it"
)

__all__ = ["GIT_BOOTSTRAP_OFFER", "GIT_BOOTSTRAP_USAGE"]
