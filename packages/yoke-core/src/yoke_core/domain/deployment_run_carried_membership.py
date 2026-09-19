"""What a run's candidate obliges it to deliver, and how that becomes membership.

The candidate already contains a delivery-ready item's merged code, so the run
deploying it owns that item's delivery whether or not anyone attached it:
leaving the item out never removed the code, only the obligation to prove it
works. This module answers that in the two ways a start needs.

:func:`enroll_carried_members` reads the run's own pinned ``release_lineage``
and admits what that commit carries, so an ordinary start completes its own
membership instead of asking a human to type the list back.
:func:`carried_membership_refusal` is the invariant behind it — what enrollment
could not resolve still stops the run, so nothing is waived by silence.

:func:`admit_run_item` is the single connection-scoped write both entrances
share: validated project/flow/stage binding, validated delivery intent, an
encoded requirement selection, and the membership row. Where no selection was
supplied it derives one from the item's outstanding post-deploy obligations
(:mod:`yoke_core.domain.deployment_member_post_deploy_admission`), so the
silence that used to mean "deliver nothing provable" now means "deliver what
this item still owes". ``cmd_add_item`` is the operator-facing adapter
around it.

Enrollment runs once per project the run ships code for — its own, plus
every project a flow stage binds — each against that project's own recorded
commit. Membership still names one item, and each item still belongs to
exactly one project; what widens is which projects a run can close out, not
what a membership row means.

Two things enrollment deliberately does not do. It never invents attribution:
an underivable carried set or an unattributed commit stays a refusal, because
enrolling from a set nobody could compute would waive coverage silently. And
it never recomputes membership a previous run already froze — a retry inherits
its predecessor's members precisely so the same candidate keeps delivering the
same items, and re-deriving would let a moved baseline rewrite that answer.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Iterable

from yoke_core.domain import db_backend
from yoke_core.domain.db_helpers import iso8601_now
from yoke_core.domain.deployment_item_flow_resolution import (
    freeze_item_completion_flow,
)
from yoke_core.domain.deployment_run_carried_work import (
    derive_carried_work_safely,
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
    which is what tells the freeze to derive again. An explicit selection is
    stored as given, and the freeze takes it as given.
    """
    validate_deployment_run_item(conn, run_id=run_id, item_id=int(item_id))
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
        (run_id, int(item_id), iso8601_now(), intent,
         None if derived else selection),
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
        return "flow_predates_release_admission"
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
) -> tuple[str, ...]:
    """Attach every delivery-ready carried item the run does not already own.

    Returns the public references actually added, in item order, so the caller
    can print exactly what the deployment gained. Raises ``ValueError`` naming
    the item and its recovery when a carried item is genuinely inadmissible —
    an incompatible flow, or a binding its own workflow refuses — because a
    run that cannot carry the obligation must not start pretending it does.
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
    payload = dict(carried_work or derive_carried_work_safely(conn, run_id))
    carried = sorted({
        int(entry["item_id"])
        for project_set in project_carried_sets(payload)
        # An underivable carried set names no items to enroll. The refusal
        # owner reports it, so silence here is deferral, not a waiver.
        if bool((project_set.get("derivation") or {}).get("contents_known"))
        for entry in project_set.get("items") or []
    })
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
        if item_id not in members
        and item_requires_release_membership(conn, item_id)
    ]
    enrolled: list[str] = []
    for item_id in candidates:
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
        f"Enrolled {len(refs)} carried delivery-ready item(s) into this "
        f"release: {', '.join(refs)}"
    )


def carried_membership_refusal(
    conn: Any,
    run_id: str,
    *,
    carried_work: Mapping[str, Any] | None = None,
) -> str | None:
    """Return an actionable refusal for unresolved or omitted deliverable code."""
    if not requires_release_admission(conn, run_id):
        return None
    if not _column_exists(conn, "deployment_runs", "composition_resolution"):
        return None
    run = conn.execute(
        f"SELECT release_lineage,composition_resolution FROM deployment_runs "
        f"WHERE id={_p(conn)}",
        (run_id,),
    ).fetchone()
    if run is None:
        return f"deployment run {run_id!r} not found"
    lineage = str(_cell(run, "release_lineage", 0) or "").strip()
    resolution = str(_cell(run, "composition_resolution", 1) or "").strip()
    if not lineage:
        return None
    payload = dict(carried_work or derive_carried_work_safely(conn, run_id))
    project_sets = project_carried_sets(payload)
    if not resolution:
        for project_set in project_sets:
            derivation = project_set.get("derivation") or {}
            reason = str(derivation.get("reason") or "unknown")
            if not bool(derivation.get("contents_known")):
                return (
                    f"deployment run {run_id!r} carried-code membership is "
                    f"{reason}; repair attribution or record "
                    "composition_resolution before execution"
                )
            bare = [str(value) for value in project_set.get("commits") or []]
            if bare:
                return (
                    f"deployment run {run_id!r} has {len(bare)} unattributed "
                    "carried commit(s); record composition_resolution "
                    "explaining their membership treatment"
                )
    if inherited_frozen_membership(conn, run_id):
        # A retry delivers exactly what its predecessor froze. Re-scanning
        # against a baseline that has moved since would name items this
        # candidate never promised, so the inherited answer stands.
        return None
    members = set(member_ids(conn, run_id))
    omitted = sorted({
        int(entry["item_id"])
        for project_set in project_sets
        for entry in project_set.get("items") or []
        if int(entry["item_id"]) not in members
        and item_requires_release_membership(conn, int(entry["item_id"]))
    })
    if not omitted:
        return None
    labels = ", ".join(
        render_item_ref(conn, int(item_id)) for item_id in omitted
    )
    why = carried_enrollment_blocked(conn, run_id) or (
        "they became deliverable after this run composed its membership"
    )
    return (
        f"deployment run {run_id!r} omits delivery-ready carried work: {labels}; "
        f"automatic enrollment did not add them ({why}). Re-run the deployment "
        "start so admission enrolls them, attach them, or choose a candidate "
        "that excludes their code. An already-done item is never one of them: "
        "it cannot be newly admitted, and its code travels under the run's "
        "pinned release lineage"
    )


__all__ = [
    "admit_run_item",
    "project_carried_sets",
    "carried_enrollment_blocked",
    "carried_membership_refusal",
    "describe_enrollment",
    "enroll_carried_members",
]
