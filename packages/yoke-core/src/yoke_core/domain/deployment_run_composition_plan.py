"""Answer a composition freeze's per-member questions before the run lock.

:func:`~yoke_core.domain.deployment_run_composition_freeze.freeze_run_composition`
asks questions whose cost grows with the run: the carried set, candidate
custody, the omitted and unclosable member refusals, and every member's
intent, selection and requirement snapshot. :func:`plan_run_composition`
asks them with no lock held and writes nothing; the freeze, holding the run
lock, writes the answers once its caller has proved them current with a
:class:`~yoke_core.domain.deployment_run_composition_basis.CompositionBasis`.

A refusal found here is kept rather than raised, and raised by the freeze at
the point its locked read would have raised it, so a run that changed state
meanwhile still answers with the refusal that state owes.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from yoke_core.domain.deployment_run_composition_freeze import (
    default_delivery_intent,
    normalize_delivery_intent,
    requires_release_admission,
)
from yoke_core.domain.workflow_delivery_binding_validation import (
    attached_binding_runtime_state,
)
from yoke_core.domain.workflow_item_binding_validation import (
    has_workflow_pin_schema,
    read_pinned_items,
)


@dataclass(frozen=True)
class MemberFreeze:
    """Every member's concrete intent, selection and snapshot, not yet written."""

    intents: dict[int, str | None]
    selections: dict[int, str]
    snapshots: dict[int, str]
    requirement_ids: tuple[int, ...]
    plan_ids: tuple[int, ...]


@dataclass(frozen=True)
class CompositionPlan:
    """A freeze's unlocked answers; see the module docstring.

    ``carried_work`` is what the freeze's own carried-work record must equal
    for the rest of the plan to stand: it is the input the custody and
    omission answers were derived from.
    """

    carried_work: Mapping[str, Any] | None
    refusal: Exception | None
    members: MemberFreeze | None
    member_refusal: Exception | None

    @property
    def requirement_ids(self) -> tuple[int, ...]:
        return self.members.requirement_ids if self.members else ()

    @property
    def plan_ids(self) -> tuple[int, ...]:
        return self.members.plan_ids if self.members else ()

    def write_members(self, conn: Any, run_id: str) -> None:
        """Raise the members' kept refusal, or write their frozen rows."""
        from yoke_core.domain.deployment_member_snapshot_write import (
            store_member_snapshots,
        )

        if self.member_refusal is not None:
            raise self.member_refusal
        assert self.members is not None
        store_member_snapshots(
            conn,
            run_id,
            self.members.selections,
            self.members.snapshots,
            intents=self.members.intents,
        )


def plan_run_composition(conn: Any, run_id: str) -> CompositionPlan | None:
    """Read what the freeze would read, without locks or writes.

    Answers ``None`` whenever the freeze would not reach its per-member
    questions, or would reach them only after a write of its own -- an
    unrecorded bound source -- so the locked freeze answers instead.
    """
    from yoke_core.domain.deployment_run_carried_work import (
        carried_work_for_enrollment,
    )
    from yoke_core.domain.deployment_run_lineage_rebind import is_full_commit

    if not requires_release_admission(conn, run_id):
        return None
    row = conn.execute(
        "SELECT release_lineage,composition_frozen_at,COALESCE(bound_sources,'') "
        "FROM deployment_runs WHERE id=%s",
        (run_id,),
    ).fetchone()
    if (
        row is None
        or row[1] not in (None, "")
        or not is_full_commit(str(row[0] or ""))
        or not str(row[2]).strip()
    ):
        return None
    carried_work = None
    refusal = None
    try:
        carried_work = carried_work_for_enrollment(conn, run_id)
        refusal = _membership_refusal(conn, run_id, carried_work)
    except (LookupError, ValueError) as exc:
        refusal = exc
    members = None
    member_refusal = None
    try:
        members = _plan_members(conn, run_id)
    except (LookupError, ValueError) as exc:
        member_refusal = exc
    return CompositionPlan(carried_work, refusal, members, member_refusal)


def _membership_refusal(
    conn: Any, run_id: str, carried_work: Mapping[str, Any]
) -> Exception | None:
    """The freeze's omitted-member and unclosable-member refusals, in order."""
    from yoke_core.domain.deployment_member_run_coverage import (
        unclosable_final_member_refusal,
    )
    from yoke_core.domain.deployment_run_carried_membership_refusal import (
        carried_membership_refusal,
    )
    from yoke_core.domain.deployment_run_unheld_candidates import (
        resolve_candidate_custody,
    )

    custody = resolve_candidate_custody(conn, run_id)
    if refusal := carried_membership_refusal(
        conn, run_id, carried_work=carried_work, custody=custody
    ):
        return ValueError(refusal)
    if refusal := unclosable_final_member_refusal(conn, run_id, custody=custody):
        return ValueError(refusal)
    return None


def _plan_members(conn: Any, run_id: str) -> MemberFreeze:
    """The unlocked half of the freeze's member write; see ``_freeze_members``."""
    from yoke_core.domain.deployment_member_snapshot_write import (
        read_member_snapshots,
        snapshot_row_ids,
    )

    members = conn.execute(
        "SELECT item_id,delivery_intent,requirement_selection "
        "FROM deployment_run_items WHERE run_id=%s ORDER BY item_id",
        (run_id,),
    ).fetchall()
    intents = {
        int(m["item_id"]): normalize_delivery_intent(m["delivery_intent"])
        for m in members
    }
    unset = [item_id for item_id, intent in intents.items() if intent is None]
    pinned = read_pinned_items(conn, unset) if has_workflow_pin_schema(conn) else None
    for item_id in unset:
        intents[item_id] = default_delivery_intent(
            None
            if pinned is None
            else attached_binding_runtime_state(conn, item_id, pinned.get(item_id))
        )
    selections, snapshots = read_member_snapshots(
        conn,
        run_id,
        {int(m["item_id"]): m["requirement_selection"] for m in members},
        lock=False,
    )
    requirement_ids, plan_ids = snapshot_row_ids(selections, snapshots)
    return MemberFreeze(intents, selections, snapshots, requirement_ids, plan_ids)


__all__ = ["CompositionPlan", "MemberFreeze", "plan_run_composition"]
