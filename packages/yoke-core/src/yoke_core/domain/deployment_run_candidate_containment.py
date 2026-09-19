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
    """
    candidate = str(candidate_lineage or "").strip()
    merge = str(commit_sha or "").strip()
    if not candidate or not merge:
        return ContainmentVerdict(
            UNDETERMINED,
            "containment_operands_missing",
            "Record both the deployed release lineage and the item's merge "
            "identity before asking whether one contains the other.",
        )
    refusals: list[tuple[str, str]] = []
    excluded: Optional[ContainmentVerdict] = None
    for opener in carried_work_sources(conn, project_id):
        try:
            source = opener()
            verdict = _ask_source(source, candidate, merge)
        except CarriedWorkSourceUnavailable as exc:
            refusals.append((exc.reason, exc.recovery))
            continue
        if verdict is None:
            refusals.append((COMMIT_UNREACHABLE, COMMIT_UNREACHABLE_RECOVERY))
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


def _ask_source(
    source: CarriedWorkSource, candidate: str, merge: str
) -> Optional[ContainmentVerdict]:
    """Ask one source both containment questions, or ``None`` if it cannot."""
    resolved_merge = source.resolve_commit(merge)
    resolved_candidate = source.resolve_commit(candidate)
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
    "ContainmentVerdict",
    "candidate_contains_commit",
]
