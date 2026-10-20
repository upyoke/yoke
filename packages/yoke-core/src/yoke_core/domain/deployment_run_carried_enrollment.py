"""One carried-enrollment decision, made before the run row lock.

:func:`~yoke_core.domain.deployment_run_carried_membership.plan_carried_enrollment`
locks the carried items and takes a
:class:`~yoke_core.domain.deployment_run_composition_basis.CompositionBasis`;
:func:`decide_carried_enrollment` then reads everything that grows with the
carried set and validates the rows it would insert. Under the run lock the
decision is confirmed with a constant re-check, or made again there.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any

from yoke_core.domain.deployment_run_composition_basis import (
    CompositionBasis,
    lock_snapshot_rows,
)
from yoke_core.domain.deployment_run_composition_freeze import (
    items_requiring_release_membership,
    member_ids,
)
from yoke_core.domain.deployment_run_dependency_readiness import (
    unshipped_dependency_pairs,
)
from yoke_core.domain.deployment_run_enrollment_error import CarriedEnrollmentError
from yoke_core.domain.deployment_run_member_admission import (
    MemberAdmission,
    RunItemsAdmission,
    prepare_run_items,
)
from yoke_core.domain.deployment_run_member_targeting import needed_member_ids
from yoke_core.domain.project_identity import render_item_ref


@dataclass(frozen=True)
class CarriedEnrollment:
    """An enrollment decided before the run row lock.

    ``refusal`` is the inadmissible candidate's error, raised only once the
    locked run is still composable. ``confirmed`` marks a decision already
    proved current under the run lock.
    """

    basis: CompositionBasis | None
    member_ids: tuple[int, ...]
    carried: tuple[int, ...]
    candidates: tuple[int, ...]
    admission: RunItemsAdmission | None
    refusal: Exception | None
    confirmed: bool = False

    @property
    def proposed_rows(self) -> dict[int, dict[str, Any]]:
        """The rows this decision inserts, for a judgement made before it does."""
        if self.admission is None or self.refusal is not None:
            return {}
        return {
            item_id: {
                "delivery_intent": self.admission.intents[item_id],
                "requirement_selection": self.admission.selections[item_id],
            }
            for item_id in self.admission.ids
        }

    @property
    def refs(self) -> tuple[str, ...]:
        if self.admission is None or self.refusal is not None:
            return ()
        return tuple(self.admission.refs[item_id] for item_id in self.candidates)

    def confirm(self, conn: Any) -> CarriedEnrollment | None:
        """Under the run lock: this decision if nothing it read has changed."""
        if self.confirmed:
            return self
        if self.basis is None:
            return None
        if self.admission is not None:
            lock_snapshot_rows(
                conn, self.admission.requirement_ids, self.admission.plan_ids
            )
        if member_ids(conn, self.basis.run_id) != self.member_ids:
            return None
        if not self.basis.unchanged(conn):
            return None
        return replace(self, confirmed=True)


@dataclass(frozen=True)
class EnrollmentOutcome:
    """What applying a decision under the run lock did.

    ``as_planned`` says the locked run took exactly the decision made before
    the lock, so a judgement made against its proposed rows still stands.
    """

    refs: tuple[str, ...]
    error: Exception | None
    as_planned: bool


def decide_carried_enrollment(
    conn: Any,
    run_id: str,
    basis: CompositionBasis | None,
    members: tuple[int, ...],
    carried_ids: tuple[int, ...],
    rebound_project_ids: frozenset[int],
    *,
    lock_reads: bool = False,
) -> CarriedEnrollment:
    """Which carried items this run admits, and their validated rows.

    ``lock_reads`` decides under the run lock, holding the rows it reads.
    """
    carried = list(carried_ids)
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
            conn, candidates, member_ids=set(members)
        )
    }
    candidates = [item_id for item_id in candidates if item_id not in blocked]
    admission = refusal = None
    try:
        admission = prepare_run_items(
            conn,
            run_id=run_id,
            members=[MemberAdmission(item_id) for item_id in candidates],
            refused=lambda item_id, exc: CarriedEnrollmentError(
                run_id, render_item_ref(conn, item_id), exc
            ),
            lock_reads=lock_reads,
        )
    except (LookupError, ValueError) as exc:
        refusal = exc
    found = tuple(candidates)
    return CarriedEnrollment(
        basis, members, carried_ids, found, admission, refusal, lock_reads
    )


__all__ = ["CarriedEnrollment", "EnrollmentOutcome", "decide_carried_enrollment"]
