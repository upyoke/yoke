"""Queue standing as the pull request itself reports it.

``mergeQueue(branch).entries`` answers from the queue's side and lists at
most a page of it. ``isInMergeQueue`` and ``mergeQueueEntry`` answer from
the pull request, so they stay correct however long the queue is, and
``mergeable`` comes back in the same read.

None of it is a substitute for the arming fact — GitHub creates the entry
only once the pull request's own required checks pass, so an armed
landing legitimately reports no entry for as long as those run. This read
is one of the three a landing needs; the caller composes them.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

from yoke_contracts.github_app_installation_permissions import (
    GITHUB_PULL_REQUESTS_READ_PERMISSION_LEVELS as PR_READ,
)

from yoke_core.domain.gh_rest_transport import split_repo
from yoke_core.engines.merge_worktree_pr_queue import (
    graphql_with_auth,
    resolve_auth_detail,
)
from yoke_core.engines.merge_worktree_prepare import MergeContext


_PR_QUEUE_MEMBERSHIP_QUERY = """
query($owner: String!, $name: String!, $number: Int!) {
  repository(owner: $owner, name: $name) {
    pullRequest(number: $number) {
      isInMergeQueue
      mergeable
      mergeQueueEntry { state }
    }
  }
}
"""


@dataclass(frozen=True)
class PrQueueMembership:
    """What the pull request says about its own queue standing."""

    in_queue: bool
    entry_state: str = ""
    mergeable: str = ""

    def describe(self) -> str:
        """The named readings behind a membership decision."""
        entry = self.entry_state or ("present" if self.in_queue else "absent")
        return (
            f"isInMergeQueue={'true' if self.in_queue else 'false'}, "
            f"mergeQueueEntry={entry}, "
            f"mergeable={self.mergeable or 'unreported'}"
        )


def read_pr_queue_membership(
    ctx: MergeContext, pr_num: str
) -> tuple[Optional[PrQueueMembership], Optional[str]]:
    """Read whether GitHub holds ``pr_num`` in a merge queue right now."""
    auth, auth_err = resolve_auth_detail(ctx, PR_READ)
    if auth_err or auth is None:
        return None, auth_err or "github auth unavailable"
    owner, name = split_repo(auth.repo)
    try:
        number = int(str(pr_num).strip())
    except ValueError:
        return None, f"pull request identifier {pr_num!r} is not a number"
    data, err = graphql_with_auth(
        auth,
        query=_PR_QUEUE_MEMBERSHIP_QUERY,
        variables={"owner": owner, "name": name, "number": number},
        required_permissions=PR_READ,
    )
    if err:
        return None, err
    pull_request = ((data or {}).get("repository") or {}).get("pullRequest")
    if not isinstance(pull_request, dict):
        return None, (
            f"repository {owner}/{name} returned no pull request {pr_num}; "
            "queue membership could not be read"
        )
    entry: Any = pull_request.get("mergeQueueEntry")
    entry_state = (
        str((entry or {}).get("state") or "") if isinstance(entry, dict) else ""
    )
    return (
        PrQueueMembership(
            in_queue=bool(pull_request.get("isInMergeQueue")),
            entry_state=entry_state,
            mergeable=str(pull_request.get("mergeable") or "").strip().upper(),
        ),
        None,
    )


__all__ = ["PrQueueMembership", "read_pr_queue_membership"]
