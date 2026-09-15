"""Commit-range facts for carried-work derivation, however the caller is hosted.

Carried work compares two release lineages. A machine holding the project's
checkout answers that comparison from git directly. A control plane serving an
HTTPS-only project holds no checkout of that project and never will, and
treating its absence as the only answer reported an unanswerable comparison as
an empty release. The repository provider answers the same questions over the
project's own authorized binding, so the same exact commit comparison runs
wherever the deriver happens to execute.

Every source answers the same four questions, and each answers them exactly:
resolve a lineage to a commit, list the first-parent range between two
commits, read one commit's message and time, and say which range commit
carries a given lane commit. A source that cannot answer raises
:class:`CarriedWorkSourceUnavailable` with the reason and the recovery rather
than returning a confident empty.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol, Sequence

from yoke_core.domain import standalone_item_merge_git as git
from yoke_core.domain.project_checkout_locations import checkout_for_project_id


SOURCE_CHECKOUT = "checkout"
SOURCE_REPOSITORY_PROVIDER = "repository_provider"

RELATION_AHEAD = "ahead"
RELATION_DIVERGED = "diverged"


class CarriedWorkSourceUnavailable(Exception):
    """No source can answer this project's commit comparison."""

    def __init__(self, reason: str, recovery: str) -> None:
        super().__init__(reason)
        self.reason = reason
        self.recovery = recovery


@dataclass(frozen=True)
class CommitRange:
    """One first-parent comparison between two release lineages."""

    relation: str
    commits: tuple[str, ...]


class CarriedWorkSource(Protocol):
    """The commit facts carried-work derivation needs, from any host."""

    origin: str

    def resolve_commit(self, ref: str) -> str:
        """Return the full commit sha for ``ref``, or ``""`` when unresolvable."""

    def lineage_relation(self, base: str, head: str) -> str:
        """Return whether ``head`` carries ``base``, without listing commits."""

    def commit_range(self, base: str, head: str) -> CommitRange:
        """Return the first-parent commits from ``base`` to ``head``."""

    def commit_message(self, sha: str) -> str:
        """Return one commit's full message."""

    def commit_time(self, sha: str) -> str:
        """Return one commit's committer time as an ISO-8601 string."""

    def carrying_commit(
        self,
        lane_commit: str,
        *,
        base: str,
        head: str,
        commits: Sequence[str],
    ) -> str:
        """Return the range commit that contains ``lane_commit``, or ``""``."""

    def warnings(self) -> list[dict[str, str]]:
        """Return degraded-source notes accumulated while answering."""


class LocalCheckoutSource:
    """Answer the comparison from a checkout this machine holds."""

    origin = SOURCE_CHECKOUT

    def __init__(self, repo_root: str) -> None:
        self._repo_root = repo_root

    def resolve_commit(self, ref: str) -> str:
        return git.git_out(
            self._repo_root, "rev-parse", "--verify", f"{ref}^{{commit}}"
        )

    def lineage_relation(self, base: str, head: str) -> str:
        return (
            RELATION_AHEAD
            if git.is_ancestor(self._repo_root, base, head)
            else RELATION_DIVERGED
        )

    def commit_range(self, base: str, head: str) -> CommitRange:
        if self.lineage_relation(base, head) == RELATION_DIVERGED:
            return CommitRange(RELATION_DIVERGED, ())
        commits = tuple(
            line.strip()
            for line in git.git_out(
                self._repo_root,
                "rev-list",
                "--first-parent",
                "--reverse",
                f"{base}..{head}",
            ).splitlines()
            if line.strip()
        )
        return CommitRange(RELATION_AHEAD, commits)

    def commit_message(self, sha: str) -> str:
        return git.git_out(self._repo_root, "show", "-s", "--format=%B", sha)

    def commit_time(self, sha: str) -> str:
        return git.git_out(self._repo_root, "show", "-s", "--format=%cI", sha)

    def carrying_commit(
        self,
        lane_commit: str,
        *,
        base: str,
        head: str,
        commits: Sequence[str],
    ) -> str:
        if git.is_ancestor(self._repo_root, lane_commit, base):
            return ""
        if not git.is_ancestor(self._repo_root, lane_commit, head):
            return ""
        for commit in commits:
            if git.is_ancestor(self._repo_root, lane_commit, commit):
                return commit
        return ""

    def warnings(self) -> list[dict[str, str]]:
        return []


def open_carried_work_source(
    conn: Any,
    project_id: int,
    *,
    repo_root: str | Path | None = None,
) -> CarriedWorkSource:
    """Return the strongest source this host can use for one project.

    A checkout the caller already named wins, then this machine's registered
    checkout, then the project's own repository provider. When none of them
    can answer, the raised reason names which authority is missing rather than
    letting the caller record an empty release.
    """
    if repo_root:
        return LocalCheckoutSource(str(repo_root))
    checkout = checkout_for_project_id(project_id)
    if checkout is not None:
        return LocalCheckoutSource(str(checkout))
    from yoke_core.domain.deployment_run_carried_work_repository import (
        open_repository_provider_source,
    )

    return open_repository_provider_source(conn, project_id)


__all__ = [
    "RELATION_AHEAD",
    "RELATION_DIVERGED",
    "SOURCE_CHECKOUT",
    "SOURCE_REPOSITORY_PROVIDER",
    "CarriedWorkSource",
    "CarriedWorkSourceUnavailable",
    "CommitRange",
    "LocalCheckoutSource",
    "open_carried_work_source",
]
