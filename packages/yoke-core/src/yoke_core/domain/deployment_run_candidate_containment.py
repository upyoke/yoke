"""Answer whether a deployed candidate contains one recorded merge commit.

A completion gate that compares an item's merge identity to the deployed
revision for equality can only ever pass a release of exactly one item: the
moment a batch ships two merges, at most one of them is the tip, and the other
is told its deployment did not target it. Containment is the question the gate
actually means, and it is a single ancestry fact about the project's own
repository rather than a chain of prior runs reasoned about after the fact.

Carried work answers a different question — what one run added over the run
before it — so it is not this answer: a run pinned to the same revision as its
predecessor legitimately carries nothing while still containing every merge
that revision contains. Both read the same comparison source, which is what
lets this hold on a control plane with no checkout of the project.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from yoke_core.domain.deployment_run_carried_work_source import (
    RELATION_AHEAD,
    CarriedWorkSourceUnavailable,
    open_carried_work_source,
)


CONTAINED = "contained"
NOT_CONTAINED = "not_contained"
UNDETERMINED = "undetermined"


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
    """Return whether ``commit_sha`` is an ancestor of ``candidate_lineage``.

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
    try:
        source = open_carried_work_source(conn, project_id)
    except CarriedWorkSourceUnavailable as exc:
        return ContainmentVerdict(UNDETERMINED, exc.reason, exc.recovery)
    resolved_merge = source.resolve_commit(merge)
    resolved_candidate = source.resolve_commit(candidate)
    if not resolved_merge or not resolved_candidate:
        return ContainmentVerdict(
            UNDETERMINED,
            "containment_commit_unreachable",
            "Make both the merge identity and the deployed lineage readable "
            "from the project's repository, then retry.",
            source=source.origin,
        )
    try:
        # Ancestry is one fact about the comparison, so it never waits on the
        # commit listing: a repository whose range is larger than a reader
        # pages still answers this truthfully.
        relation = source.lineage_relation(resolved_merge, resolved_candidate)
    except CarriedWorkSourceUnavailable as exc:
        return ContainmentVerdict(UNDETERMINED, exc.reason, exc.recovery, source.origin)
    state = CONTAINED if relation == RELATION_AHEAD else NOT_CONTAINED
    return ContainmentVerdict(state, source=source.origin)


__all__ = [
    "CONTAINED",
    "NOT_CONTAINED",
    "UNDETERMINED",
    "ContainmentVerdict",
    "candidate_contains_commit",
]
