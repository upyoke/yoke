"""Commit-range facts for carried-work derivation, however the caller is hosted.

Carried work compares two release lineages. A machine holding the project's
checkout answers that comparison from git directly. A control plane serving an
HTTPS-only project holds no checkout of that project and never will, and
treating its absence as the only answer reported an unanswerable comparison as
an empty release. The repository provider answers the same questions over the
project's own authorized binding, so the same exact commit comparison runs
wherever the deriver happens to execute.

Every source answers the same questions, and each answers them exactly:
resolve a lineage to a commit, list the first-parent range between two
commits, read one commit's message and time, say which range commit carries a
given lane commit, and answer the two containment questions — is this commit
in that revision's history, and would merging it change that revision at all.
A source that cannot answer raises :class:`CarriedWorkSourceUnavailable` with
the reason and the recovery, or answers ``None`` where the caller has another
rung, rather than returning a confident empty.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Optional, Protocol, Sequence

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
    #: Where this source reads — a checkout path, or the repository binding.
    #: A refusal that cannot name the place it looked sends its reader
    #: hunting for one, so every source says which place answered it.
    location: str

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

    def contains_commit(self, candidate: str, commit: str) -> Optional[bool]:
        """Whether ``candidate``'s history already holds ``commit``.

        The same ancestry :meth:`lineage_relation` answers, asked the way
        containment means it and answered without listing the range between
        the two — a release-sized listing is megabytes, and this is one bit.
        """

    def adds_nothing(self, candidate: str, commit: str) -> Optional[bool]:
        """Whether merging ``commit`` into ``candidate`` would change it.

        ``None`` when this source cannot say, which containment reads as
        this source having no answer at all rather than as a no. Work that
        reached the base under other commit ids is contained in content
        while failing every ancestry test, so containment asks this once
        ancestry says no.
        """

    def warnings(self) -> list[dict[str, str]]:
        """Return degraded-source notes accumulated while answering."""


class LocalCheckoutSource:
    """Answer the comparison from a checkout this machine holds."""

    origin = SOURCE_CHECKOUT

    def __init__(self, repo_root: str) -> None:
        self._repo_root = repo_root
        self.location = repo_root
        self._fetched = False
        self._warnings: list[dict[str, str]] = []

    def resolve_commit(self, ref: str) -> str:
        resolved = self._rev_parse(ref)
        if resolved:
            return resolved
        # A checkout holds only the commits it has already fetched, so a pin
        # recorded after its last fetch is indistinguishable from a commit
        # that never existed. Ask the remote once before answering that it is
        # unreachable; a run whose pins are already present never gets here,
        # so the comparison that can answer still costs no network at all.
        if self._fetch():
            return self._rev_parse(ref)
        return ""

    def _rev_parse(self, ref: str) -> str:
        return git.git_out(
            self._repo_root, "rev-parse", "--verify", f"{ref}^{{commit}}"
        )

    def _fetch(self) -> bool:
        """Refresh this checkout's remote-tracking refs, at most once.

        Opportunistic, never required: refreshing is something a checkout
        may be able to do, not something the comparison depends on. The
        remote, the credential, and the network bound are the ones lane
        preparation already fetches through, and only remote-tracking refs
        move — no local branch, ref, or working tree is touched. A checkout
        that cannot name a remote, has no credential for it, or has no
        network keeps answering from the refs it already holds and records
        why, so a later refusal is the ordinary named one rather than a
        new failure mode.
        """
        if self._fetched:
            return False
        self._fetched = True
        from yoke_cli.config import repo_upstream_git

        branch = git.git_out(self._repo_root, "branch", "--show-current")
        remote, configured = repo_upstream_git.resolve_remote(
            self._repo_root, branch
        )
        if not remote:
            self._note_unfetched(
                "no remote is configured for this checkout"
                if configured == 0
                else (
                    f"{configured} remotes are configured and none is recorded "
                    f"for this branch"
                )
            )
            return False
        fetched = repo_upstream_git.git(
            self._repo_root,
            "fetch",
            "--no-tags",
            remote,
            timeout=repo_upstream_git.network_timeout_seconds(),
        )
        if fetched.returncode != 0:
            self._note_unfetched(
                f"fetching {remote} failed: "
                f"{repo_upstream_git.reason(fetched)}"
            )
            return False
        return True

    def _note_unfetched(self, detail: str) -> None:
        self._warnings.append(
            {
                "reason": "checkout_not_refreshed",
                "recovery": (
                    f"Checkout {self._repo_root} answered from the refs it "
                    f"already held ({detail}); a commit recorded after its "
                    "last fetch reads as unreachable."
                ),
                "error_type": "",
            }
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

    def contains_commit(self, candidate: str, commit: str) -> Optional[bool]:
        return git.is_ancestor(self._repo_root, commit, candidate)

    def adds_nothing(self, candidate: str, commit: str) -> Optional[bool]:
        # The merge boundary's own definition, called rather than restated.
        adds_nothing = git.lane_adds_nothing(self._repo_root, commit, candidate)
        if adds_nothing is not None:
            return adds_nothing
        # That answers ``None`` for a conflict and for a git it could not
        # run, and those are not the same fact: a merge that conflicts is a
        # merge that changes the base, which is the definition of adding
        # something. Separating them here keeps a genuinely excluded
        # candidate a definite refusal instead of an unreadable one.
        conflicts = git.lane_merge_conflicts(self._repo_root, commit, candidate)
        return False if conflicts else None

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
        return list(self._warnings)


def carried_work_sources(
    conn: Any,
    project_id: int,
    *,
    repo_root: str | Path | None = None,
) -> tuple[Callable[[], CarriedWorkSource], ...]:
    """Every source this host can try for one project, strongest first.

    A checkout the caller already named, then this machine's registered
    checkout, then the project's own repository provider. Returned as openers
    rather than sources because opening the provider itself can fail, and a
    caller walking the list needs that failure as one more reason it could
    not answer rather than as the end of the walk.

    Order is preference, not exclusivity: a caller that cannot get its answer
    from one source asks the next, because these sources fail for unrelated
    reasons — a checkout missing a commit it never fetched, a provider read
    that timed out — and either can hold the answer the other lacks.
    """
    openers: list[Callable[[], CarriedWorkSource]] = []
    named = str(repo_root) if repo_root else ""
    if named:
        openers.append(lambda: LocalCheckoutSource(named))
    checkout = checkout_for_project_id(project_id)
    if checkout is not None and str(checkout) != named:
        openers.append(lambda: LocalCheckoutSource(str(checkout)))

    def _provider() -> CarriedWorkSource:
        from yoke_core.domain.deployment_run_carried_work_repository import (
            open_repository_provider_source,
        )

        return open_repository_provider_source(conn, project_id)

    openers.append(_provider)
    return tuple(openers)


def open_carried_work_source(
    conn: Any,
    project_id: int,
    *,
    repo_root: str | Path | None = None,
) -> CarriedWorkSource:
    """Return the strongest source this host can use for one project.

    The derivation reads a whole commit range from one source, so it takes
    the first that opens. When none of them can answer, the raised reason
    names which authority is missing rather than letting the caller record an
    empty release.
    """
    openers = carried_work_sources(conn, project_id, repo_root=repo_root)
    for index, opener in enumerate(openers):
        try:
            return opener()
        except CarriedWorkSourceUnavailable:
            if index == len(openers) - 1:
                raise
    raise CarriedWorkSourceUnavailable(
        "project_source_unavailable",
        "This host offers no source for the project's commit comparison.",
    )


__all__ = [
    "RELATION_AHEAD",
    "RELATION_DIVERGED",
    "SOURCE_CHECKOUT",
    "SOURCE_REPOSITORY_PROVIDER",
    "CarriedWorkSource",
    "CarriedWorkSourceUnavailable",
    "CommitRange",
    "LocalCheckoutSource",
    "carried_work_sources",
    "open_carried_work_source",
]
