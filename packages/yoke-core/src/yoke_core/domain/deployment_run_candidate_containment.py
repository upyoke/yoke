"""Answer whether a deployed candidate contains one recorded merge commit.

A completion gate that compares an item's merge identity to the deployed
revision for equality can only ever pass a release of exactly one item: the
moment a batch ships two merges, at most one of them is the tip, and the other
is told its deployment did not target it. Containment is the question the gate
actually means.

It is two questions, asked in order. Ancestry answers almost every case: the
candidate's history holds the commit. Content answers the rest — a lane whose
commits reached the base under other identities, through a companion item's
landing or a rebase, adds nothing to the candidate while failing every
ancestry test. That second question is the merge boundary's own "this lane
adds nothing", asked of the same source rather than defined again here.

Both run against every source this host can offer, because they fail for
unrelated reasons: a checkout can lack a commit it never fetched while the
provider holds it, and a provider read can time out on a range a checkout
answers instantly. Only when no source answers is the verdict undetermined,
and then it names every reason it collected.

A source answers "not contained" only when it answered BOTH questions and
both said no. One that could not run the content question has not excluded
anything — the very case it exists to catch is a lane the candidate already
carries under other commit ids — so it is undetermined for that source and
the walk moves on to the next.

Carried work answers a different question — what one run added over the run
before it — so it is not this answer: a run pinned to the same revision as its
predecessor legitimately carries nothing while still containing every merge
that revision contains. Both read the same comparison sources, which is what
lets this hold on a control plane with no checkout of the project.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

from yoke_core.domain.deployment_run_carried_work_source import (
    CarriedWorkSource,
    CarriedWorkSourceUnavailable,
    carried_work_sources,
)


CONTAINED = "contained"
NOT_CONTAINED = "not_contained"
UNDETERMINED = "undetermined"

#: Why a source that opened still could not answer.
COMMIT_UNREACHABLE = "containment_commit_unreachable"
COMMIT_UNREACHABLE_RECOVERY = (
    "Make both the merge identity and the deployed lineage readable from "
    "the project's repository, then retry."
)


@dataclass(frozen=True)
class ContainmentVerdict:
    """One ancestry answer, or a named reason there is no answer."""

    state: str
    reason: str = ""
    recovery: str = ""
    source: str = ""

    @property
    def contained(self) -> bool:
        return self.state == CONTAINED


class CandidateContainment:
    """Ask one candidate lineage about many commits, opening sources once.

    Containment is asked per commit, but the sources that answer it are per
    project and per candidate: the same checkout, and the same resolution of
    the same candidate revision, serve every commit in the batch. Opening
    them per commit re-forked one ``rev-parse`` of the identical candidate
    for every card on a roster, which is the cost this exists to stop paying.

    A source is opened at most once. One that refuses to open keeps its named
    refusal and contributes it to every commit's undetermined verdict, so a
    batched walk collects exactly the reasons a per-commit walk did.
    """

    def __init__(
        self,
        conn: Any,
        project_id: int,
        *,
        candidate_lineage: str,
        source: Optional[CarriedWorkSource] = None,
    ) -> None:
        self._candidate = str(candidate_lineage or "").strip()
        self._openers = (
            (lambda: source,)
            if source is not None
            else carried_work_sources(conn, project_id)
        )
        self._opened: Optional[list[_OpenedSource]] = None

    def _sources(self) -> list["_OpenedSource"]:
        """Open every source once, keeping each refusal as its own answer."""
        if self._opened is None:
            opened: list[_OpenedSource] = []
            for opener in self._openers:
                try:
                    source = opener()
                except CarriedWorkSourceUnavailable as exc:
                    opened.append(_OpenedSource(None, (exc.reason, exc.recovery)))
                    continue
                opened.append(_OpenedSource(source, None))
            self._opened = opened
        return self._opened

    def contains(self, commit_sha: str) -> ContainmentVerdict:
        """Return whether the candidate already carries ``commit_sha``."""
        merge = str(commit_sha or "").strip()
        if not self._candidate or not merge:
            return _operands_missing()
        refusals: list[tuple[str, str]] = []
        excluded: Optional[ContainmentVerdict] = None
        for entry in self._sources():
            if entry.source is None:
                refusals.append(entry.refusal or ("", ""))
                continue
            verdict = _ask_source(
                entry.source,
                entry.resolved_candidate(self._candidate),
                merge,
            )
            if verdict is None:
                refusals.append(
                    (COMMIT_UNREACHABLE, COMMIT_UNREACHABLE_RECOVERY),
                )
                continue
            if verdict.contained:
                return verdict
            # A definite exclusion is an answer, but a weaker one than a yes: a
            # source that cannot merge trees answers "not contained" for work
            # another source recognises as already present. So keep the answer
            # and keep asking.
            excluded = excluded or verdict
        if excluded is not None:
            return excluded
        return _undetermined(refusals)


@dataclass
class _OpenedSource:
    """One source's open outcome, plus the candidate resolution it caches.

    The candidate is the same revision for every commit in the batch, so its
    resolution is asked of each source once and reused. A source that cannot
    resolve it keeps the empty answer, which ``_ask_source`` reads as this
    source having no answer exactly as a per-commit walk did.
    """

    source: Optional[CarriedWorkSource]
    refusal: Optional[tuple[str, str]]
    _candidate_sha: Optional[str] = None

    def resolved_candidate(self, candidate: str) -> str:
        if self._candidate_sha is None:
            assert self.source is not None
            self._candidate_sha = self.source.resolve_commit(candidate)
        return self._candidate_sha


def _operands_missing() -> ContainmentVerdict:
    return ContainmentVerdict(
        UNDETERMINED,
        "containment_operands_missing",
        "Record both the deployed release lineage and the item's merge "
        "identity before asking whether one contains the other.",
    )


def candidate_contains_commit(
    conn: Any,
    project_id: int,
    *,
    candidate_lineage: str,
    commit_sha: str,
) -> ContainmentVerdict:
    """Return whether ``candidate_lineage`` already carries ``commit_sha``.

    A revision contains itself, so the single-item release the equality test
    used to be the only passing case stays a passing case.

    An unanswerable comparison is ``UNDETERMINED`` with the reason and the
    recovery, never ``NOT_CONTAINED``: a caller that cannot look has not
    learned that the candidate excludes the merge, and a gate that treats the
    two alike refuses correct releases for as long as the source is missing.

    Asking about several commits against one candidate is
    :class:`CandidateContainment`, which opens the sources once instead of
    once per commit.
    """
    return CandidateContainment(
        conn,
        project_id,
        candidate_lineage=candidate_lineage,
    ).contains(commit_sha)


def _ask_source(
    source: CarriedWorkSource, resolved_candidate: str, merge: str
) -> Optional[ContainmentVerdict]:
    """Ask one source both containment questions, or ``None`` if it cannot.

    The candidate arrives already resolved because it is the same revision
    for every commit the caller asks about; the merge is this question's own
    and is resolved here.
    """
    resolved_merge = source.resolve_commit(merge)
    if not resolved_merge or not resolved_candidate:
        return None
    contained = source.contains_commit(resolved_candidate, resolved_merge)
    if contained:
        return ContainmentVerdict(CONTAINED, source=source.origin)
    adds_nothing = source.adds_nothing(resolved_candidate, resolved_merge)
    if adds_nothing:
        return ContainmentVerdict(
            CONTAINED,
            reason="the commit adds nothing the candidate does not have",
            source=source.origin,
        )
    if adds_nothing is None:
        # Ancestry said no, and the content question — the one that catches a
        # lane whose work reached the base under other commit ids — went
        # unanswered. That is this source not knowing, not this source
        # excluding the merge, and a caller told "not contained" on it would
        # send an owner to redeploy work the release already shipped.
        return None
    return ContainmentVerdict(NOT_CONTAINED, source=source.origin)


def _undetermined(refusals: list[tuple[str, str]]) -> ContainmentVerdict:
    """Name every source's reason, because each one is separately fixable."""
    if not refusals:
        return ContainmentVerdict(
            UNDETERMINED,
            "containment_source_unavailable",
            "This host offers no source that can compare the project's "
            "commits; register a checkout or authorize its repository "
            "binding, then retry.",
        )
    seen: dict[str, str] = {}
    for reason, recovery in refusals:
        seen.setdefault(reason, recovery)
    return ContainmentVerdict(
        UNDETERMINED,
        ", ".join(seen),
        " ".join(recovery for recovery in seen.values() if recovery),
    )


__all__ = [
    "CONTAINED",
    "NOT_CONTAINED",
    "UNDETERMINED",
    "CandidateContainment",
    "ContainmentVerdict",
    "candidate_contains_commit",
]
