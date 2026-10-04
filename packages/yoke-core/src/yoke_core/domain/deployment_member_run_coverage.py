"""What a deployment run can do for one member, said while the attach is open.

Membership is admitted on facts about the code — this run ships the item's
project, the item is delivery-ready — and both are silent about whether this
particular run can do anything with the member once it holds it. Two
independent capabilities decide that, and a run can have either, both, or
neither:

* **Check** it. Only an item-scoped QA stage runs a case against a member,
  freezes its requirement snapshot, or collects evidence for it. Stages are
  only ``execution`` or ``qa``, so a flow whose QA stages are all run-scoped
  answers for the release as a whole and never for a member: nothing on it is
  ever about this item.
* **Close** it, which is :func:`membership_closes_item` — the item's own
  completion flow, or another project's run carrying this project's source.

Neither implies the other, so this reports two facts rather than one verdict.
Most flows in service check nothing and close everything they carry, and that
is correct: a flow with no item-scoped QA stage is how most items are
delivered and closed, which is exactly why the missing stage alone is no
reason to refuse an attach.

A run that can do neither is the case worth naming. The member receives
nothing from it — and it is not merely inert, because membership is what puts
a landing in custody (:mod:`yoke_core.domain.delivery_landing_custody`), and a
held landing is one the next start on the item's completion flow will not
enroll. The real release stops proposing the item while a run that can never
close it holds it.

So this warns instead of refusing, and it says both halves rather than a
boolean: a refusal would have to pick one of two facts the caller needs, and
would reject the ordinary delivery every project depends on. It also does not
gate on the release-admission schema version. The post-deploy admission
notice beside it is silent on version-1 definitions by design, and a
version-1 definition is what this warning exists for.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Sequence

from yoke_core.domain import db_backend
from yoke_core.domain.deployment_run_composition_freeze import (
    member_ids,
    requires_release_admission,
)
from yoke_core.domain.deployment_run_unheld_candidates import (
    CustodyResolution,
    held_candidate_ids,
)

#: Where a run with delivery custody is a final delivery rather than a preview.
FINAL_DELIVERY_TIER = "persistent"


def _p(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def _cell(row: Any, key: str, index: int) -> Any:
    return row[key] if hasattr(row, "keys") else row[index]


@dataclass(frozen=True)
class MemberRunCoverage:
    """The two things one run can or cannot do for one member."""

    item_ref: str
    run_id: str
    run_flow: str
    completion_flow: str
    #: Stages on this run's flow that will answer for this member by name.
    item_scoped_stages: tuple[str, ...]
    closes: bool

    @property
    def checks(self) -> bool:
        return bool(self.item_scoped_stages)

    @property
    def inert(self) -> bool:
        """Whether this run can neither check the member nor close it.

        An item that resolves no completion flow at all is deliberately not
        inert here. Nothing could close it on any run, so this is not the
        wrong run — it is the already-owned fault that delivery clearance
        refuses with its own reason, and claiming it here would turn one
        fault into a second, worse-placed warning naming the wrong repair.
        """
        return bool(self.completion_flow) and not self.checks and not self.closes


def member_run_coverage(conn: Any, *, run_id: str, item_id: int) -> MemberRunCoverage:
    """The one-member form of the set-based coverage reader."""
    from yoke_core.domain.deployment_member_coverage_batch import member_run_coverages

    return member_run_coverages(conn, run_id=run_id, item_ids=(item_id,))[int(item_id)]


def _check_clause(coverage: MemberRunCoverage) -> str:
    if coverage.checks:
        named = ", ".join(repr(name) for name in coverage.item_scoped_stages)
        return f"asks this member to answer for itself at QA stage {named}"
    return (
        "declares no item-scoped stage, so no case runs against this member, "
        "no evidence is collected for it, and no requirement snapshot freezes"
    )


def _close_clause(coverage: MemberRunCoverage) -> str:
    if coverage.closes:
        if coverage.run_flow == coverage.completion_flow:
            return "is this item's completion flow, so it can close the item"
        return "carries this item's project source, so it can close the item"
    if not coverage.completion_flow:
        # Said plainly, without this notice's recovery: a flow that resolves
        # nowhere is delivery clearance's refusal to name, not this one's.
        return (
            "cannot close the item, because the item resolves no completion flow at all"
        )
    return (
        f"cannot close the item, whose completion flow is {coverage.completion_flow!r}"
    )


def _inert_consequence(coverage: MemberRunCoverage) -> str:
    """Name what an achieves-nothing membership still does, and the way out."""
    return (
        "This membership therefore achieves nothing, and it is not free: "
        "while this run is live or succeeded and its candidate carries the "
        f"item's merge, {coverage.item_ref} counts as held by a release, so "
        f"the next start on {coverage.completion_flow!r} will not enroll it. "
        f"Attach the item to a run of {coverage.completion_flow!r} instead, "
        "or leave it out and let that flow's next start enroll it from its "
        "own candidate — yoke deployment-runs validate-composition RUN-ID "
        "composes that run now. If this run is not one you need, "
        f"yoke deployment-runs terminalize {coverage.run_id} --disposition "
        "cancelled --reason REASON releases the hold; a cancelled run holds "
        "no landing."
    )


def describe_member_run_coverage(coverage: MemberRunCoverage) -> str:
    """State what this member will and will not receive from this run."""
    head = (
        f"{coverage.item_ref} on run {coverage.run_id}: flow "
        f"{coverage.run_flow!r} {_check_clause(coverage)}, and it "
        f"{_close_clause(coverage)}."
    )
    if not coverage.inert:
        return head
    return f"{head} {_inert_consequence(coverage)}"


def member_coverage_notice(conn: Any, *, run_id: str, item_id: int) -> str:
    """The attach-time line for one member: both facts, always said.

    The attach is the last moment a caller can choose a different run, so it
    gets the whole answer rather than only the bad half of it.
    """
    return describe_member_run_coverage(
        member_run_coverage(conn, run_id=str(run_id), item_id=int(item_id))
    )


def inert_membership_notice(
    conn: Any, run_id: str, *, item_ids: Sequence[int] | None = None
) -> str:
    """Name every member this run can neither check nor close, or ``''``.

    The run-wide preview names only those: a run that can close its members
    is the ordinary case, and restating it per member would bury the one
    membership that will receive nothing.
    """
    subjects: Iterable[int] = (
        member_ids(conn, run_id)
        if item_ids is None
        else tuple(int(v) for v in item_ids)
    )
    from yoke_core.domain.deployment_member_coverage_batch import member_run_coverages

    notices = [
        describe_member_run_coverage(coverage)
        for coverage in member_run_coverages(
            conn, run_id=run_id, item_ids=subjects
        ).values()
        if coverage.inert
    ]
    return " ".join(notices)


def _final_delivery_run(conn: Any, run_id: str) -> bool:
    """Whether this run is a release that finally delivers its members.

    Custody alone does not say so: an ephemeral preview takes custody of what
    it carries without owing anyone their done. A persistent-tier release
    does, and it is the one that can turn green over a member it cannot close.
    """
    if not requires_release_admission(conn, run_id):
        return False
    row = conn.execute(
        "SELECT COALESCE(NULLIF(dr.target_tier, ''), df.target_tier, '') "
        "FROM deployment_runs dr LEFT JOIN deployment_flows df ON df.id = dr.flow "
        f"WHERE dr.id = {_p(conn)}",
        (str(run_id),),
    ).fetchone()
    return row is not None and str(row[0] or "") == FINAL_DELIVERY_TIER


def unclosable_final_member_refusal(
    conn: Any, run_id: str, *, custody: CustodyResolution | None = None
) -> str | None:
    """Refuse a release whose success would leave a final member open.

    Membership admits an item on facts about the code; closing it takes
    completion authority (:func:`membership_closes_item`). A same-project run
    of another flow holds the member, runs its QA, turns green, and cannot
    close it — the member then waits for a delivery that already happened.
    Said before execution, while the item's flow or the run can still change.

    A member another live or succeeded release already holds is not one of
    them. That run owes the delivery and answers for the close; this one is
    only carrying its ancestor code, so refusing here would block every
    release cut over a live one for a member it was never delivering.

    Pass *custody* to reuse a resolution the caller already walked.
    """
    if not _final_delivery_run(conn, run_id):
        return None
    held = held_candidate_ids(conn, run_id, custody=custody)
    from yoke_core.domain.deployment_member_coverage_batch import (
        final_open_member_ids,
        member_run_coverages,
    )

    subjects = tuple(
        item_id
        for item_id in final_open_member_ids(conn, run_id)
        if item_id not in held
    )
    unclosable = [
        coverage
        for item_id, coverage in member_run_coverages(
            conn, run_id=run_id, item_ids=member_ids(conn, run_id)
        ).items()
        if item_id in subjects
        # No completion flow at all is completion_flow_refusal's to name.
        if coverage.completion_flow and not coverage.closes
    ]
    if not unclosable:
        return None
    run_flow = unclosable[0].run_flow
    named = "; ".join(
        f"{coverage.item_ref} selects completion flow {coverage.completion_flow!r}"
        for coverage in unclosable
    )
    first = unclosable[0].item_ref
    return (
        f"deployment run {run_id!r} on flow {run_flow!r} is the final delivery "
        f"of members it has no authority to close: {named}. Succeeding would "
        "leave them open at their release wait. Reconcile before execution: "
        "when this run is the delivery they should close on, select its flow "
        f"(`yoke items scalar update {first} --field deployment_flow --value "
        f"{run_flow}`, once per member) and re-run `yoke deployment-runs "
        f"validate-composition {run_id}`; otherwise cancel it (`yoke "
        f"deployment-runs terminalize {run_id} --disposition cancelled "
        "--reason REASON`) and deliver them through a run of their own flow."
    )


__all__ = [
    "MemberRunCoverage",
    "describe_member_run_coverage",
    "inert_membership_notice",
    "member_coverage_notice",
    "member_run_coverage",
    "unclosable_final_member_refusal",
]
