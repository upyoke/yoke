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

:func:`admit_run_item` is the single connection-scoped write both entrances
share: validated project/flow/stage binding, validated delivery intent, an
encoded requirement selection, and the membership row. Where no selection was
supplied it derives one from the item's outstanding post-deploy obligations
(:mod:`yoke_core.domain.deployment_member_post_deploy_admission`), so the
silence that used to mean "deliver nothing provable" now means "deliver what
this item still owes". ``cmd_add_item`` is the operator-facing adapter
around it.

Enrollment checks each shipped project's recorded commit. Membership still
names one item in one project; the run may close items across bound projects.

Two things enrollment deliberately does not do. It never invents attribution:
an underivable carried set or an unattributed commit stays a refusal, because
enrolling from a set nobody could compute would waive coverage silently. And
it never recomputes membership a previous run already froze — a retry inherits
its predecessor's members so the same candidate keeps delivering the same
items, and re-deriving would let a moved baseline rewrite that answer.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Iterable

from yoke_core.domain import db_backend
from yoke_core.domain.db_helpers import iso8601_now
from yoke_core.domain.deployment_item_flow_resolution import (
    completion_flow_refusal,
    freeze_item_completion_flow,
)
from yoke_core.domain.deployment_run_carried_work import (
    carried_work_for_enrollment,
)
from yoke_core.domain.deployment_member_post_deploy_admission import (
    admissible_post_deploy_requirement_ids,
)
from yoke_core.domain.deployment_run_composition_freeze import (
    inherited_frozen_membership,
    item_requires_release_membership,
    member_ids,
    requires_release_admission,
    validate_delivery_intent_for_item,
)
from yoke_core.domain.deployment_run_composition_guard import (
    has_frozen_composition,
)
from yoke_core.domain.deployment_run_membership_removals import (
    removed_item_ids,
)
from yoke_core.domain.deployment_run_dependency_readiness import (
    unshipped_dependency_pairs,
)
from yoke_core.domain.deployment_run_unheld_candidates import (
    CustodyResolution,
    resolve_candidate_custody,
)
from yoke_core.domain.deployment_runs_lock import lock_run
from yoke_core.domain.deployment_requirement_snapshots import (
    requirement_selection,
    snapshot_member_requirements,
)
from yoke_core.domain.project_identity import render_item_ref
from yoke_core.domain.schema_common import _column_exists
from yoke_core.domain.workflow_delivery_binding_validation import (
    validate_deployment_run_item,
)
from yoke_core.domain.workflow_item_binding_lock import (
    lock_item_workflow_bindings,
)


def _p(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def _cell(row: Any, key: str, index: int) -> Any:
    return row[key] if hasattr(row, "keys") else row[index]


def admit_run_item(
    conn: Any,
    *,
    run_id: str,
    item_id: int,
    delivery_intent: str | None = None,
    requirement_ids: Iterable[int] = (),
    plan_ids: Iterable[int] = (),
) -> str:
    """Insert one validated membership row in the caller's transaction.

    The caller owns the commit, which is what lets enrollment land inside the
    same transaction that freezes the composition it just completed.

    A membership with nothing selected takes on the item's outstanding
    post-deploy obligations, because a post_deploy row is answered by this
    run's admitted copy and by nothing else: an empty selection would ship
    the code while leaving the obligation unanswerable. An explicit
    selection is a deliberate operator choice and is used verbatim.

    A derived list is validated here but not stored: it answers "what does
    this item still owe", and an obligation minted between this row and the
    composition freeze belongs in it. The column is therefore left null,
    which tells the freeze to derive again. An explicit selection is stored
    as given, and the freeze takes it as given.
    """
    validate_deployment_run_item(conn, run_id=run_id, item_id=int(item_id))
    if requires_release_admission(conn, run_id):
        if refusal := completion_flow_refusal(conn, int(item_id)):
            raise ValueError(refusal)
    freeze_item_completion_flow(conn, int(item_id))
    intent = validate_delivery_intent_for_item(conn, int(item_id), delivery_intent)
    selected_requirements = tuple(requirement_ids)
    selected_plans = tuple(plan_ids)
    derived = not selected_requirements and not selected_plans
    if derived:
        selected_requirements = admissible_post_deploy_requirement_ids(
            conn, run_id=run_id, item_id=int(item_id)
        )
    selection = requirement_selection(
        requirement_ids=selected_requirements, plan_ids=selected_plans
    )
    # Validated now so an unusable obligation refuses here rather than at the
    # freeze, even though a derived list is not what gets stored.
    snapshot_member_requirements(
        conn, run_id=run_id, item_id=int(item_id), selection_json=selection
    )
    conn.execute(
        "INSERT INTO deployment_run_items "
        "(run_id, item_id, added_at, delivery_intent, requirement_selection) "
        "VALUES (%s, %s, %s, %s, %s)",
        (run_id, int(item_id), iso8601_now(), intent, None if derived else selection),
    )
    return render_item_ref(conn, int(item_id))


def project_carried_sets(payload: Mapping[str, Any]) -> tuple[Mapping[str, Any], ...]:
    """Every project answer inside one carried-work record, own project first.

    Callers ask the same three questions of each — was it derivable, which
    items did it carry, which commits stayed unattributed — so the shape is
    walked rather than special-cased per project.
    """
    bound = payload.get("bound_projects") or []
    return (payload, *(entry for entry in bound if isinstance(entry, Mapping)))


def carried_enrollment_blocked(conn: Any, run_id: str) -> str:
    """Name why this run enrolls nothing, or ``''`` when it may enroll."""
    if not requires_release_admission(conn, run_id):
        return "flow_without_delivery_custody"
    if not _column_exists(conn, "deployment_runs", "composition_resolution"):
        return "composition_schema_unconverged"
    if has_frozen_composition(conn, run_id):
        return "composition_already_frozen"
    if inherited_frozen_membership(conn, run_id):
        return "membership_inherited_from_frozen_run"
    return ""


def enroll_carried_members(
    conn: Any,
    run_id: str,
    *,
    carried_work: Mapping[str, Any] | None = None,
    custody: CustodyResolution | None = None,
) -> tuple[str, ...]:
    """Attach every delivery-ready carried item the run does not already own.

    Returns the public references actually added, in item order, so the caller
    can print exactly what the deployment gained. Raises ``ValueError`` naming
    the item and its recovery when a carried item is genuinely inadmissible —
    an incompatible flow, or a binding its own workflow refuses — because a
    run that cannot carry the obligation must not start pretending it does.

    Pass *custody* to reuse a resolution the caller already walked. Resolving
    it here is still done before any lock below is taken, because the walk
    reaches GitHub and the run row must never be held across a network call.
    """
    if carried_enrollment_blocked(conn, run_id):
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
    if lock_run(conn, run_id) != "created":
        # Membership is mutable only while a run is composable, and the run
        # row now says it is not. Nothing was written.
        return ()
    if carried_enrollment_blocked(conn, run_id):
        return ()
    members = set(member_ids(conn, run_id))
    candidates = [
        item_id
        for item_id in carried
        if item_id not in members and item_requires_release_membership(conn, item_id)
    ]
    blocked = {
        dependent for dependent, _, _ in unshipped_dependency_pairs(conn, candidates)
    }
    enrolled: list[str] = []
    for item_id in candidates:
        if item_id in blocked:
            continue
        try:
            enrolled.append(admit_run_item(conn, run_id=run_id, item_id=item_id))
        except (LookupError, ValueError) as exc:
            raise ValueError(
                f"deployment run {run_id!r} carries "
                f"{render_item_ref(conn, item_id)} but cannot admit it: {exc}; "
                "align that item's deployment flow and stage with this run, or "
                "choose a candidate that excludes its code"
            ) from exc
    return tuple(enrolled)


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
    "admit_run_item",
    "project_carried_sets",
    "carried_enrollment_blocked",
    "describe_enrollment",
    "enroll_carried_members",
]
