"""Delivery-ready landings this run's candidate carries, split by who holds them.

Carried work answers "what did this run add over the run before it", and that
is the whole candidate set enrollment used to have. It is a question about a
commit RANGE, so it has a floor: the preceding succeeded release's lineage. A
landing behind that floor is outside every future range permanently. Once the
only run that ever named such an item ends without delivering it — cancelled,
superseded — nothing can propose it again, and three items sat at their
release wait for a day because the sole remaining recovery was an operator
remembering to attach them by hand.

This module asks the question that actually serves delivery, and it asks it
without a floor: of the landings this candidate carries, which does no live or
succeeded release hold, and which does one already hold? The unheld half is
unioned into enrollment beside the carried range, so a run start completes its
own membership whether the work landed since the last release or long before
it. The held half is the exclusion the carried range cannot make for itself:
that range is pure commit arithmetic, so it proposes an ancestor landing
another live run is mid-delivery on, and composing it would put two runs on
one obligation — and, where the holder's flow differs from this one's, refuse
the whole creation over a member this run was never meant to carry.

Three things it deliberately does not do:

* It does not widen what "deliverable" means. Every candidate still passes
  ``item_requires_release_membership`` — the same pinned-workflow delivery
  readiness check every other admission uses.
* It does not enroll code this run is not shipping. Containment against the
  run's own pinned lineage is required, so a merge that landed after the
  candidate was pinned waits for the release that actually carries it.
* It does not re-enroll a landing somebody already holds. Custody lives in
  :mod:`delivery_landing_custody` and is asked per landing, so an item that
  merged again after joining a run enrolls for the new merge while one
  already being delivered is left alone.

Custody is always asked with this run excluded. A run reasoning about its own
composition that counted its own membership would read every member it already
holds as held elsewhere, which would silently retire the final-member
completion-authority refusal rather than narrow it.

Answering it costs a source walk per carried project -- a GitHub containment
question, so network I/O with no bound of its own. Four different composition
readers need the same answer, and asking four times once put three of those
walks inside the run row lock that enrollment had already taken: a laptop that
hibernated mid-walk pinned the row until a human terminated the backend.
:func:`resolve_candidate_custody` hands every reader one
:class:`CustodyResolution`, which walks at most once and only when a reader
that got past its own preconditions actually asks. Because custody is asked
with ``exclude_run_id`` set to this run, enrolling its own members cannot
change the answer, so one resolution stays valid for the whole composition.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from yoke_core.domain.delivery_landing_custody import (
    landing_custody,
    merged_open_items,
)
from yoke_core.domain.deployment_run_candidate_containment import (
    UNDETERMINED,
    CandidateContainment,
)
from yoke_core.domain.deployment_run_composition_freeze import (
    item_requires_release_membership,
)
from yoke_core.domain.deployment_run_project_sources import (
    carried_project_ids,
    run_source_sha,
)
from yoke_core.domain.project_identity import render_item_ref


@dataclass(frozen=True)
class HeldCandidate:
    """A landing this candidate carries that another release already holds."""

    item_id: int
    item_ref: str
    #: The live or succeeded run whose candidate carries this landing.
    run_id: str
    run_status: str


@dataclass(frozen=True)
class CandidateCustody:
    """This candidate's deliverable landings, split by who owes the delivery."""

    #: Item ids no other live or succeeded release holds.
    enrollable: tuple[int, ...]
    held: tuple[HeldCandidate, ...]

    @property
    def held_ids(self) -> frozenset[int]:
        return frozenset(record.item_id for record in self.held)


def candidate_custody(conn: Any, run_id: str) -> CandidateCustody:
    """Split what this run's candidate carries into unheld and held landings.

    Walks every project the run ships code for, because membership follows
    the code: a run binding another project's source delivers that project's
    merges too. Each project is asked against the commit THIS run pinned for
    it, never against a lineage belonging to the carrier.
    """
    enrollable: set[int] = set()
    held: list[HeldCandidate] = []
    for project_id in carried_project_ids(conn, run_id):
        lineage = run_source_sha(conn, run_id, int(project_id))
        if not lineage:
            continue
        found, holders = _project_custody(
            conn, run_id, project_id=int(project_id), lineage=lineage
        )
        enrollable.update(found)
        held.extend(holders)
    return CandidateCustody(
        enrollable=tuple(sorted(enrollable)),
        held=tuple(sorted(held, key=lambda record: record.item_id)),
    )


class CustodyResolution:
    """One candidate-custody answer, walked at most once and shared by readers.

    Lazy on purpose, and that is the whole contract. Every reader gates on its
    own preconditions first -- a run with no release lineage, a frozen or
    inherited composition, a delivery that is not this run's final one -- and
    several return before custody is relevant at all. Walking eagerly on the
    caller's behalf would reach the project source for runs that never asked,
    which is both a wasted round trip and a new failure mode: a universe whose
    schema cannot answer the question would start refusing compositions that
    never needed it. Resolving on first use keeps each reader's precondition
    exactly where it was while still costing one walk for all of them.

    The walk is therefore triggered by whichever reader needs it first, and
    enrollment -- the only reader that takes the run row lock -- needs it
    before it locks. So the network round trip stays outside the lock whether
    enrollment resolves it or skips it.
    """

    __slots__ = ("_conn", "_run_id", "_custody", "_refusal", "_walked")

    def __init__(self, conn: Any, run_id: str) -> None:
        self._conn = conn
        self._run_id = run_id
        self._custody: CandidateCustody | None = None
        self._refusal: str | None = None
        self._walked = False

    def _resolve(self) -> None:
        """Walk custody once, keeping an unanswerable one as a named refusal.

        Enrollment must raise on that -- it would otherwise compose a
        membership it could not justify -- while the readers that only *narrow*
        a report must not, because a lost narrowing beats a raised reader.
        Holding both lets each keep the behaviour it already had.
        """
        if self._walked:
            return
        self._walked = True
        try:
            self._custody = candidate_custody(self._conn, self._run_id)
        except (LookupError, ValueError) as exc:
            self._refusal = str(exc)

    def require(self) -> CandidateCustody:
        """Return the custody, or raise the refusal that prevented answering."""
        self._resolve()
        if self._custody is None:
            raise ValueError(self._refusal or "candidate custody is undetermined")
        return self._custody

    @property
    def held_ids(self) -> frozenset[int]:
        """Held landings, empty when custody could not be determined."""
        self._resolve()
        return self._custody.held_ids if self._custody is not None else frozenset()

    @property
    def held(self) -> tuple[HeldCandidate, ...]:
        """Held landings in item order, empty when custody is undetermined."""
        self._resolve()
        return self._custody.held if self._custody is not None else ()


def resolve_candidate_custody(conn: Any, run_id: str) -> CustodyResolution:
    """Hand back the shared custody answer for *run_id*, unwalked.

    Build this before taking any run or binding lock and pass it to every
    consumer: the walk it defers reaches the project source, and no network
    round trip belongs inside a row lock a deploy is holding.
    """
    return CustodyResolution(conn, run_id)


def unheld_candidate_ids(conn: Any, run_id: str) -> tuple[int, ...]:
    """Item ids this run should enroll that its carried range cannot see."""
    return candidate_custody(conn, run_id).enrollable


def held_candidate_ids(
    conn: Any, run_id: str, *, custody: CustodyResolution | None = None
) -> frozenset[int]:
    """Carried landings another release holds, empty when custody cannot say.

    A composition reader must not be turned into a raise by a custody question
    it does not own: enrollment reports an unanswerable custody by name, so
    withholding the exclusion here loses the narrowing rather than the error.

    Pass *custody* to reuse a resolution the caller already walked.
    """
    return (custody or resolve_candidate_custody(conn, run_id)).held_ids


def held_candidate_notice(
    conn: Any, run_id: str, *, custody: CustodyResolution | None = None
) -> str:
    """Name every carried landing this run left out because a release holds it.

    Said whenever composition reports itself, because "why is my item not a
    member" is otherwise answerable only by reading two runs' membership by
    hand. Silent when this run may not enroll at all: nothing was skipped.

    Pass *custody* to reuse a resolution the caller already walked.
    """
    from yoke_core.domain.deployment_run_carried_membership import (
        carried_enrollment_blocked,
    )

    if carried_enrollment_blocked(conn, run_id):
        return ""
    held = (custody or resolve_candidate_custody(conn, run_id)).held
    if not held:
        return ""
    named = "; ".join(
        f"{record.item_ref} held by {record.run_id} ({record.run_status})"
        for record in held
    )
    return (
        f"Skipped {len(held)} delivery-ready item(s) this candidate carries "
        f"that a release already holds: {named}. Each is that run's delivery "
        "to finish; this one composes nothing for it"
    )


def _project_custody(
    conn: Any, run_id: str, *, project_id: int, lineage: str
) -> tuple[set[int], list[HeldCandidate]]:
    """One project's deliverable landings inside this candidate, split by holder."""
    deliverable = [
        int(record["id"])
        for record in merged_open_items(conn, project_id)
        if item_requires_release_membership(conn, int(record["id"]))
    ]
    if not deliverable:
        return set(), []
    custody = landing_custody(
        conn,
        project_id=project_id,
        item_ids=deliverable,
        exclude_run_id=str(run_id),
    )
    walker = CandidateContainment(conn, project_id, candidate_lineage=lineage)
    found: set[int] = set()
    held: list[HeldCandidate] = []
    for item_id in deliverable:
        landing = custody[item_id]
        if landing.state == UNDETERMINED:
            raise ValueError(
                f"deployment run {run_id!r} cannot determine custody of "
                f"{render_item_ref(conn, item_id)}: {landing.reason}. "
                f"{landing.recovery}"
            )
        if not landing.landing_sha:
            raise ValueError(
                f"deployment run {run_id!r} cannot attribute "
                f"{render_item_ref(conn, item_id)}: its merged landing has no "
                "commit identity; repair its merge receipt and retry"
            )
        verdict = walker.contains(landing.landing_sha)
        if verdict.state == UNDETERMINED:
            raise ValueError(
                f"deployment run {run_id!r} cannot compare the pinned "
                f"candidate with {render_item_ref(conn, item_id)}: "
                f"{verdict.reason}. {verdict.recovery}"
            )
        if not verdict.contained:
            continue
        if landing.held:
            held.append(
                HeldCandidate(
                    item_id=item_id,
                    item_ref=render_item_ref(conn, item_id),
                    run_id=landing.run_id,
                    run_status=landing.run_status,
                )
            )
        elif landing.enrollable:
            found.add(item_id)
    return found, held


__all__ = [
    "CandidateCustody",
    "CustodyResolution",
    "HeldCandidate",
    "candidate_custody",
    "held_candidate_ids",
    "held_candidate_notice",
    "resolve_candidate_custody",
    "unheld_candidate_ids",
]
