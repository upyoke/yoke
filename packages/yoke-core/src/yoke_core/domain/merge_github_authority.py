"""Which GitHub authority a merge needs, settled before the merge starts.

A merge reaches GitHub two ways, and they do not need the same authority. A
direct merge lands the branch in the checkout, publishes the base branch with
the machine's stored GitHub credential (:mod:`yoke_cli.config.credentialed_git`
carries it, so the publish authenticates the same way the clone that created
the checkout did), and then proves the pushed commit's checks — all of it work
the project's App installation is authorized to do on its own.
Creating a pull request is attributed to a person, so it needs this machine's
GitHub App *user* authorization and nothing else stands in for it.

Naming that before any merge work is what keeps an unavailable authorization
from being discovered after the branch has already landed: admission refuses a
route whose authority cannot be resolved, and the post-push proof that follows
a landed merge asks for the same authority the merge itself ran under rather
than for the strictest one available.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

from yoke_contracts.github_app_installation_permissions import (
    GITHUB_CHECKS_READ_PERMISSION_LEVELS,
    GITHUB_PULL_REQUESTS_WRITE_PERMISSION_LEVELS,
)
from yoke_core.domain import standalone_item_merge_git as git
from yoke_core.domain.project_github_auth_models import (
    GITHUB_AUTHORITY_INSTALLATION,
    GITHUB_AUTHORITY_USER,
)


DIRECT_MERGE_ROUTE = "direct_merge"
PULL_REQUEST_MERGE_ROUTE = "pull_request_merge"

_ROUTE_LABELS = {
    DIRECT_MERGE_ROUTE: "direct merge",
    PULL_REQUEST_MERGE_ROUTE: "pull-request merge",
}
_AUTHORITY_LABELS = {
    GITHUB_AUTHORITY_INSTALLATION: (
        "the project's GitHub App installation"
    ),
    GITHUB_AUTHORITY_USER: (
        "this machine's GitHub App user authorization"
    ),
}


@dataclass(frozen=True)
class MergeAuthority:
    """The authority and repository permission one merge route requires."""

    route: str
    authority: str
    permissions: Mapping[str, str]

    @property
    def user_authorization_required(self) -> bool:
        return self.authority == GITHUB_AUTHORITY_USER

    def describe(self) -> str:
        """One line naming the route and the authority it is admitted under."""
        route = _ROUTE_LABELS.get(self.route, self.route)
        authority = _AUTHORITY_LABELS.get(self.authority, self.authority)
        return f"{route}, authorized by {authority}"


def classify_merge_authority(*, local_merge: bool) -> MergeAuthority:
    """Name the authority a merge needs from the route it will take."""
    if local_merge:
        return MergeAuthority(
            route=DIRECT_MERGE_ROUTE,
            authority=GITHUB_AUTHORITY_INSTALLATION,
            permissions=GITHUB_CHECKS_READ_PERMISSION_LEVELS,
        )
    return MergeAuthority(
        route=PULL_REQUEST_MERGE_ROUTE,
        authority=GITHUB_AUTHORITY_USER,
        permissions=GITHUB_PULL_REQUESTS_WRITE_PERMISSION_LEVELS,
    )


def merge_reaches_github(
    *, local_merge: bool, standalone: bool, repo_root: str,
) -> bool:
    """Whether this merge needs GitHub at all, and so needs admitting.

    A pull-request merge always does. A direct merge does once it is a
    standalone landing in a checkout that has a remote, because that boundary
    publishes the base branch and then proves the pushed commit's checks; with
    no remote the merge never leaves the machine, and a project with no GitHub
    binding must still be able to merge locally.
    """
    if not local_merge:
        return True
    if not standalone:
        return False
    return git.has_remote(repo_root)


__all__ = [
    "DIRECT_MERGE_ROUTE",
    "PULL_REQUEST_MERGE_ROUTE",
    "MergeAuthority",
    "classify_merge_authority",
    "merge_reaches_github",
]
