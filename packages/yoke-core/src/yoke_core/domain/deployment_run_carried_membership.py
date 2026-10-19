"""What a run's candidate obliges it to deliver, and how that becomes membership.

The candidate contains merged code, so the run owns delivery whether or not
anyone attached its item. This module answers at start and composition freeze.

:func:`enroll_carried_members` reads the run's own pinned ``release_lineage``
and admits what that commit carries, so an ordinary start completes its own
membership instead of asking a human to type the list back. Its candidate set
is :mod:`deployment_run_unheld_candidates` reconciled with the carried range:
that range has a floor at the previous succeeded release, so the unheld
landings are unioned in to reach what it cannot see, and the landings a live or
succeeded release already holds are subtracted, because commit arithmetic
happily proposes an ancestor another run is mid-delivery on. Everything left is
filtered by the same admission rules below.
:mod:`deployment_run_carried_membership_refusal` is the invariant behind it —
what enrollment could not resolve still stops the run, so nothing is waived by
silence, and it makes the same subtraction so the two can never disagree.

:func:`~yoke_core.domain.deployment_run_member_admission.admit_run_items`
is the single connection-scoped write every entrance shares; enrollment
admits its whole candidate set through one call.

Enrollment checks each shipped project's recorded commit. Membership still
names one item in one project; the run may close items across bound projects.

Two things enrollment deliberately does not do. It never invents attribution:
an underivable carried set stays a refusal, because enrolling from an unknown
set would waive coverage silently. Commits no item owns ship as recorded
commits made outside Yoke. And
it preserves membership a previous run already froze. An unused consumer
refresh may admit newly carried members while retaining existing acceptance
contracts and every other project's recorded source facts.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Iterable

from yoke_core.domain.deployment_run_member_targeting import needed_member_ids
from yoke_core.domain.deployment_start_timing import start_step
from yoke_core.domain.deployment_run_carried_work import (
    carried_work_for_enrollment,
)
from yoke_core.domain.deployment_run_composition_freeze import (
    inherited_frozen_membership,
    items_requiring_release_membership,
    member_ids,
    requires_release_admission,
)
from yoke_core.domain.deployment_run_composition_guard import (
    has_frozen_composition,
)
from yoke_core.domain.deployment_run_member_admission import (
    MemberAdmission,
    admit_run_items,
)
from yoke_core.domain.deployment_run_membership_removals import (
    removed_item_ids,
)
from yoke_core.domain.deployment_run_enrollment_error import (
    CarriedEnrollmentError,
)
from yoke_core.domain.deployment_run_dependency_readiness import (
    unshipped_dependency_pairs,
)
from yoke_core.domain.deployment_run_unheld_candidates import (
    CustodyResolution,
    resolve_candidate_custody,
)
from yoke_core.domain.deployment_runs_lock import lock_run
from yoke_core.domain.project_identity import render_item_ref
from yoke_core.domain.workflow_item_binding_lock import (
    lock_item_workflow_bindings,
)


def project_carried_sets(payload: Mapping[str, Any]) -> tuple[Mapping[str, Any], ...]:
    """Every project answer inside one carried-work record, own project first.

    Callers ask the same three questions of each — was it derivable, which
    items did it carry, which commits stayed unattributed — so the shape is
    walked rather than special-cased per project.
    """
    bound = payload.get("bound_projects") or []
    return (payload, *(entry for entry in bound if isinstance(entry, Mapping)))


def carried_enrollment_blocked(
    conn: Any, run_id: str, *, refreshing_bound_sources: bool = False
) -> str:
    """Name why this run enrolls nothing, or ``''`` when it may enroll."""
    if not requires_release_admission(conn, run_id):
        return "flow_without_delivery_custody"
    if not refreshing_bound_sources and has_frozen_composition(conn, run_id):
        return "composition_already_frozen"
    if not refreshing_bound_sources and inherited_frozen_membership(conn, run_id):
        return "membership_inherited_from_frozen_run"
    return ""


def enroll_carried_members(
    conn: Any,
    run_id: str,
    *,
    carried_work: Mapping[str, Any] | None = None,
    custody: CustodyResolution | None = None,
    rebound_project_ids: frozenset[int] = frozenset(),
) -> tuple[str, ...]:
    """Attach every delivery-ready carried item the run does not already own.

    Returns the public references actually added, in item order, so the caller
    can print exactly what the deployment gained. Raises
    ``CarriedEnrollmentError`` naming the item, its cause and recovery when a
    carried item is genuinely inadmissible —
    an incompatible flow, or a binding its own workflow refuses — because a
    run that cannot carry the obligation must not start pretending it does.

    Pass *custody* to reuse a resolution the caller already walked. Resolving
    it here is still done before any lock below is taken, because the walk
    reaches GitHub and the run row must never be held across a network call.
    """
    if carried_enrollment_blocked(
        conn, run_id, refreshing_bound_sources=bool(rebound_project_ids)
    ):
        return ()
    row = conn.execute(
        "SELECT COALESCE(release_lineage,'') FROM deployment_runs WHERE id=%s",
        (run_id,),
    ).fetchone()
    if row is None:
        raise LookupError(f"deployment run {run_id!r} not found")
    if not str(row[0] or "").strip():
        return ()
    payload = dict(carried_work or carried_work_for_enrollment(conn, run_id))
    resolved = (custody or resolve_candidate_custody(conn, run_id)).require()
    # An underivable carried set names no items to enroll. The refusal owner
    # reports it, so silence here is deferral, not a waiver.
    range_ids = {
        int(entry["item_id"])
        for project_set in project_carried_sets(payload)
        if bool((project_set.get("derivation") or {}).get("contents_known"))
        for entry in project_set.get("items") or []
    }
    # A held landing belongs to the release already delivering it; an unheld
    # one below the range's floor is still this run's to deliver. Both are
    # reconciled into one candidate set before any lock is taken.
    # An operator's recorded removal outranks both sources: the code still
    # ships, but this run was told the item is not its to deliver.
    carried = sorted(
        ((range_ids - resolved.held_ids) | set(resolved.enrollable))
        - removed_item_ids(conn, run_id)
    )
    if not carried:
        return ()
    # Item workflow bindings first, then the run row: the same order
    # ``lock_run_with_stable_membership`` and ``cmd_add_item`` take, so a
    # manual admission and this one can never hold each other's next lock.
    # Every carried item is locked, not only the ones eligible a moment ago,
    # because eligibility is exactly what the lock has to hold still — an
    # item this read called terminal could otherwise become deliverable
    # between the decision and the insert.
    lock_item_workflow_bindings(conn, carried + list(member_ids(conn, run_id)))
    allowed_statuses = (
        {"created", "executing", "failed"} if rebound_project_ids else {"created"}
    )
    if lock_run(conn, run_id) not in allowed_statuses:
        # Membership is mutable only while a run is composable, and the run
        # row now says it is not. Nothing was written.
        return ()
    if carried_enrollment_blocked(
        conn, run_id, refreshing_bound_sources=bool(rebound_project_ids)
    ):
        return ()
    members = set(member_ids(conn, run_id))
    needed = needed_member_ids(conn, run_id=run_id, item_ids=carried)
    if rebound_project_ids:
        rows = conn.execute(
            "SELECT id,project_id FROM items WHERE id=ANY(%s)", (carried,)
        ).fetchall()
        carried = sorted(
            int(row[0]) for row in rows if int(row[1]) in rebound_project_ids
        )
    required = items_requiring_release_membership(conn, carried)
    candidates = [
        item_id
        for item_id in carried
        if item_id not in members and item_id in required and item_id in needed
    ]
    blocked = {
        dependent
        for dependent, _, _ in unshipped_dependency_pairs(
            conn, candidates, member_ids=members
        )
    }
    candidates = [item_id for item_id in candidates if item_id not in blocked]
    with start_step(
        "enrollment_members", heartbeat=True, record_count=len(candidates)
    ) as progress:
        enrolled = admit_run_items(
            conn,
            run_id=run_id,
            members=[MemberAdmission(item_id) for item_id in candidates],
            refused=lambda item_id, exc: CarriedEnrollmentError(
                run_id, render_item_ref(conn, item_id), exc
            ),
        )
        progress["completed_count"] = len(enrolled)
    return tuple(enrolled[item_id] for item_id in candidates)


def describe_enrollment(enrolled: Iterable[str]) -> str:
    """Render the one line that names what a deployment start just enrolled."""
    refs = [str(ref) for ref in enrolled]
    if not refs:
        return ""
    return (
        f"Enrolled {len(refs)} delivery-ready item(s) this candidate carries "
        f"and no release held, into this "
        f"release: {', '.join(refs)}"
    )


__all__ = [
    "project_carried_sets",
    "carried_enrollment_blocked",
    "describe_enrollment",
    "enroll_carried_members",
]
