"""Read one repository comparison response, or refuse to read it at all.

Every field here is load-bearing, and every gap in one is a reason to answer
"unknown" rather than "empty". A status this reader does not recognize, an
absent commit total, and a missing listing each mean the comparison did not
say what the range holds; treating any of them as a default would let a
malformed body authorize a completion or record an empty release.
"""

from __future__ import annotations

from typing import Any, Mapping

from yoke_core.domain.deployment_run_carried_work_source import (
    RELATION_AHEAD,
    RELATION_DIVERGED,
    CarriedWorkSourceUnavailable,
)


# ``status`` describes the head relative to the base, and the base is the
# older lineage: a head carrying it is ahead of it, or identical to it.
CONTAINING_STATUSES = frozenset({"ahead", "identical"})
DIVERGED_STATUSES = frozenset({"behind", "diverged"})
#: ``status`` read from the base's side: the head is behind the base, or the
#: two are the same commit, exactly when the base contains the head.
BASE_CONTAINING_STATUSES = frozenset({"behind", "identical"})
#: ``status`` read from the base's side when the head carries commits the
#: base does not and the base carries none the head lacks.
STRICTLY_AHEAD_STATUS = "ahead"
FULL_SHA_LENGTH = 40


def incomplete(detail: str) -> CarriedWorkSourceUnavailable:
    """Build the one refusal every unread comparison fact raises."""
    return CarriedWorkSourceUnavailable(
        "repository_provider_comparison_incomplete",
        f"{detail}; retry once the provider is healthy.",
    )


def relation(status: str) -> str:
    if status in CONTAINING_STATUSES:
        return RELATION_AHEAD
    return RELATION_DIVERGED


def head_adds_commits(status: str) -> bool:
    """Whether the head is strictly ahead of the base, read from the base.

    The base is then an ancestor of the head, so merging the head into it
    fast-forwards to the head's own tree. That makes "does this add
    anything" answerable from the status alone — no blob has to be priced —
    which is what keeps an ordinary older release a definite exclusion
    rather than an unreadable one.
    """
    return status == STRICTLY_AHEAD_STATUS


def base_contains_head(status: str) -> bool:
    """Whether the comparison's BASE already holds everything its head does.

    The mirror of :func:`relation`, for the one question containment asks:
    a base that the head is ``behind``, or that is ``identical`` to it, has
    the head's history. Asked in this direction on purpose — comparing the
    older commit as the base lists every commit and file between the two,
    which is megabytes for a release-sized range, while the same question
    asked of the newer commit as the base lists nothing at all.
    """
    return status in BASE_CONTAINING_STATUSES


def require_status(body: Mapping[str, Any]) -> str:
    status = str(body.get("status") or "").strip()
    if status not in CONTAINING_STATUSES and status not in DIVERGED_STATUSES:
        raise incomplete(
            f"the comparison reported status {status!r}, which this reader "
            "does not recognize"
        )
    return status


def require_total(body: Mapping[str, Any]) -> int:
    total = body.get("total_commits")
    if isinstance(total, bool) or not isinstance(total, int) or total < 0:
        raise incomplete("the comparison omitted its commit total")
    return total


def require_commits(body: Mapping[str, Any]) -> list[Any]:
    commits = body.get("commits")
    if not isinstance(commits, list):
        raise incomplete("the comparison omitted its commit listing")
    return commits


def recorded_commit(entry: Any) -> dict[str, dict[str, Any]]:
    """Read one commit entry, refusing one that cannot carry the graph.

    Skipping a malformed entry loses the fact that it was malformed: the
    first-parent walk and the attribution reachability both read parents,
    so an entry recorded without them truncates a chain silently and the
    result reads as a shorter release rather than an unread one. Every
    commit strictly between two lineages has a parent — a root commit
    cannot be in a range whose base is its own ancestor — so an entry
    without one is a broken comparison, not a boundary.
    """
    if not isinstance(entry, Mapping):
        raise incomplete("the comparison listed a commit that is not an object")
    sha = str(entry.get("sha") or "").strip().lower()
    if len(sha) != FULL_SHA_LENGTH or not is_hex(sha):
        raise incomplete(
            f"the comparison listed a commit with an unusable sha {sha!r}"
        )
    commit = entry.get("commit")
    commit = commit if isinstance(commit, Mapping) else {}
    committer = commit.get("committer")
    committer = committer if isinstance(committer, Mapping) else {}
    parents = entry.get("parents")
    if not isinstance(parents, list):
        raise incomplete(f"the comparison listed commit {sha} without parents")
    if not parents:
        raise incomplete(
            f"the comparison listed commit {sha} with no usable parent"
        )
    # Parent ORDER is the whole meaning of a first-parent walk, so a parent
    # that cannot be read is never dropped: skipping an unreadable first
    # parent promotes the second one into its place and the walk follows a
    # merged side branch as though it were the trunk, reporting a different
    # release rather than an unread one.
    parent_shas = tuple(_parent_sha(parent, sha, index) for index, parent in enumerate(parents))
    return {
        sha: {
            "message": str(commit.get("message") or ""),
            "committed_at": str(committer.get("date") or ""),
            "parents": parent_shas,
        }
    }


def _parent_sha(parent: Any, sha: str, index: int) -> str:
    """Read one parent at its own position, holding it to the commit's bar."""
    candidate = ""
    if isinstance(parent, Mapping):
        candidate = str(parent.get("sha") or "").strip().lower()
    if len(candidate) != FULL_SHA_LENGTH or not is_hex(candidate):
        raise incomplete(
            f"the comparison listed commit {sha} with an unusable parent "
            f"{candidate!r} at position {index}"
        )
    return candidate


def is_hex(value: str) -> bool:
    try:
        int(value, 16)
    except ValueError:
        return False
    return True


__all__ = [
    "BASE_CONTAINING_STATUSES",
    "CONTAINING_STATUSES",
    "DIVERGED_STATUSES",
    "STRICTLY_AHEAD_STATUS",
    "base_contains_head",
    "head_adds_commits",
    "incomplete",
    "is_hex",
    "recorded_commit",
    "relation",
    "require_commits",
    "require_status",
    "require_total",
]
