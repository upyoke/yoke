"""Train-composition admission for merge-queue entry.

The merge queue batches whatever is queued, so composition is enforced at
the door: the merge boundary calls :func:`evaluate_admission` with the
candidate and the items already queued, and only enqueues on ``admit``.
Pure logic over pre-fetched shapes — callers gather inputs through the
registered read surfaces (path-claim listings, dependency listings, the
item's DB-mutation profile) so this module stays transport-free and
unit-testable.

Rules, in refusal-priority order:

1. **Serial ordering** — a candidate linked to a queued member by a
   non-``coordination_only`` dependency edge (either direction) waits while
   that edge's predecessor has not yet landed; order-dependent items ride
   separate trains. An edge whose predecessor already landed has had its
   order fixed by that landing, so a later correction of either item — a
   follow-up pull request on an item that already merged — is no longer
   ordered against the other and co-queues freely.
2. **Path overlap** — a candidate whose claimed path targets intersect a
   queued member's claim must carry a ``coordination_only`` attestation
   for that member pair; un-attested overlap refuses admission.
3. **Migration carriers** — at most one member with a declared governed
   DB mutation per train. The migration coordination lease already
   serializes rehearsal upstream; this rule keeps two carriers from
   landing in one combined apply window.

Operator waiver and hotfix bypasses live outside this module: the branch
ruleset's bypass actors and the requirement-scoped QA waiver surface are
upstream of queue entry, and an operator who bypasses the queue never
reaches admission at all.
"""

from __future__ import annotations

from dataclasses import dataclass, field


ADMIT = "admit"
REFUSE_SERIAL_ORDERING = "serial-ordering"
REFUSE_UNATTESTED_OVERLAP = "unattested-path-overlap"
REFUSE_MIGRATION_CARRIER = "migration-carrier-limit"


@dataclass(frozen=True)
class TrainCandidate:
    """One item's admission-relevant shape.

    ``claimed_target_ids`` are canonical ``path_targets`` ids from the
    item's non-terminal claims — ids, not path strings, so symlink pairs
    and renames compare the way registration-time overlap already does.
    ``migration_carrier`` reflects ``db_mutation_profile.state != "none"``.
    ``landed`` reflects a recorded ``merged_at``: the item already merged
    once, so a queued branch for it is a same-item correction.
    """

    public_ref: str
    claimed_target_ids: frozenset[int] = frozenset()
    migration_carrier: bool = False
    landed: bool = False


@dataclass(frozen=True)
class AdmissionVerdict:
    admit: bool
    reason: str
    conflicting_members: tuple[str, ...] = ()

    def narrative(self) -> str:
        if self.admit:
            return "admission clear: no queued member conflicts"
        members = ", ".join(self.conflicting_members) or "queued members"
        refusal = f"admission refused ({self.reason}) against {members}"
        if self.reason == REFUSE_SERIAL_ORDERING:
            refusal += (
                ": the dependency edge's predecessor has not landed yet. "
                "Wait for that landing, then re-run `yoke merge item`"
            )
        return refusal


@dataclass(frozen=True)
class TrainContext:
    """Queue-side facts the caller resolved before the admission call.

    ``coordination_attested_refs`` — members whose shared-path overlap
    with the candidate is attested by a ``coordination_only``
    ``item_dependencies`` row (authored at planning/refine time).
    ``predecessor_refs`` — members the candidate depends on, and
    ``dependent_refs`` — members that depend on the candidate, each through
    a non-``coordination_only`` dependency edge.
    """

    members: tuple[TrainCandidate, ...] = ()
    coordination_attested_refs: frozenset[str] = frozenset()
    predecessor_refs: frozenset[str] = frozenset()
    dependent_refs: frozenset[str] = frozenset()
    notes: tuple[str, ...] = field(default=())


def evaluate_admission(
    candidate: TrainCandidate,
    context: TrainContext,
) -> AdmissionVerdict:
    """Classify whether ``candidate`` may co-queue with current members."""
    serial = tuple(
        member.public_ref
        for member in context.members
        if (member.public_ref in context.predecessor_refs and not member.landed)
        or (member.public_ref in context.dependent_refs and not candidate.landed)
    )
    if serial:
        return AdmissionVerdict(
            admit=False,
            reason=REFUSE_SERIAL_ORDERING,
            conflicting_members=serial,
        )

    overlapping = tuple(
        member.public_ref
        for member in context.members
        if candidate.claimed_target_ids & member.claimed_target_ids
        and member.public_ref not in context.coordination_attested_refs
    )
    if overlapping:
        return AdmissionVerdict(
            admit=False,
            reason=REFUSE_UNATTESTED_OVERLAP,
            conflicting_members=overlapping,
        )

    if candidate.migration_carrier:
        carriers = tuple(
            member.public_ref for member in context.members if member.migration_carrier
        )
        if carriers:
            return AdmissionVerdict(
                admit=False,
                reason=REFUSE_MIGRATION_CARRIER,
                conflicting_members=carriers,
            )

    return AdmissionVerdict(admit=True, reason=ADMIT)


__all__ = [
    "ADMIT",
    "REFUSE_MIGRATION_CARRIER",
    "REFUSE_SERIAL_ORDERING",
    "REFUSE_UNATTESTED_OVERLAP",
    "AdmissionVerdict",
    "TrainCandidate",
    "TrainContext",
    "evaluate_admission",
]
