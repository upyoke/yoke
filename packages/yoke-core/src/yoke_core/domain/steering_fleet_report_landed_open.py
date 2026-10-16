"""Items whose branch landed while the item never reached a terminal status.

Landing is not finishing. A merged item still owes a close-out, and where the
project delivers through releases it owes a delivery first — so this section
exists to name the gap between "the code is on the base branch" and "the item
is done".

What a seat reads and does about each row is
:mod:`steering_fleet_report_landed_phrases`.

The custody answer comes from :mod:`delivery_landing_custody`, which run
enrollment reads too. That sharing is the point: what the report calls
stranded is exactly what the next release start will enroll, so the seat is
never told to chase something the product was about to do by itself.

The holder answer comes from :mod:`steering_fleet_report_holders`, for the
same reason and after the same failure. This section used to run its own
narrower claim query one line after the report had already built the full
holder facts, and that second reader knew only the session id — so park state
was not omitted by choice, it was unreachable, and every landed row printed a
close-out command whether or not anybody needed one. A second reader that
knows less than the first and wins anyway is the shape of the defect; the
repair is to stop asking a question that was already answered better.
"""

from __future__ import annotations

from datetime import datetime

from dataclasses import dataclass
from typing import Any, Sequence

from yoke_core.domain.deployment_item_flow_resolution import item_completion_flow_facts
from yoke_core.domain.deployment_flow_state import FLOW_STATUS_ACTIVE
from yoke_core.domain import db_backend
from yoke_core.domain.delivery_landing_custody import (
    ENROLLABLE_CUSTODY_STATES,
    HELD,
    REMERGED,
    UNHELD,
    landed_at,
    landing_custody,
    merged_open_items,
)
from yoke_core.domain.deployment_run_member_targeting import run_environment_name
from yoke_core.domain.deployment_run_other_target_members import (
    owed_on_other_targets,
)
from yoke_core.domain.item_ref_render import render_item_refs
from yoke_core.domain.runs import RunStatus
from yoke_core.domain.session_item_stage_rework import items_returned_after_landing
from yoke_core.domain.steering_fleet_report_detectors import age_seconds
from yoke_core.domain.steering_fleet_report_holders import ClaimHolder


@dataclass(frozen=True)
class LandedItem:
    """One item whose branch landed while the item stayed open."""

    item_id: int
    public_ref: str
    status: str
    landed_at: datetime | None
    landed_seconds: int
    #: The live session holding the item's claim, empty when none does.
    #: Close-out is a claim-holding step, so this is the difference between
    #: a landing its holder will finish and one that needs staffing.
    holder_session_id: str = ""
    #: Whether that holder is parked. A parked holder is waiting on the
    #: delivery its close-out needs, so the row is healthy and wants no
    #: command: a recovery offered where none is needed reads as work.
    holder_parked: bool = False
    #: The parked holder's own words for what it waits on, when it left any.
    holder_quiet_reason: str = ""
    #: Seconds since that holder's last tool call. Quiet past the report's
    #: idle threshold after landing means a holder is not driving close-out;
    #: a declared release wait expects tool silence.
    holder_idle_seconds: int = 0
    #: The workflow the item pins, because close-out is composed from it: an
    #: evidence-gated terminal transition refuses the bare command.
    workflow_id: str = ""
    #: Which release holds THIS landing, from :mod:`delivery_landing_custody`.
    #: Without it every landed row read alike, and an item stranded by a
    #: cancelled run looked exactly like one mid-delivery — which is why it
    #: took a person noticing three day-old rows to find the last ones.
    custody_state: str = UNHELD
    #: The run the state is about: the holder, or the run a re-merge left
    #: behind. Empty when no release names the item at all.
    custody_run_id: str = ""
    #: The resolved closing flow is active; an absent/disabled flow cannot deliver.
    completion_flow_available: bool = False
    holder_native_process_gone: bool = False
    #: The holder's process state in the shared holder wording, or ``""``
    #: while its process is live.
    holder_process_phrase: str = ""
    #: A message resumes the holder's exited native from its transcript.
    holder_resumable: bool = False
    #: Where a succeeded holder run delivered this landing, ``""`` otherwise,
    #: and each requirement it still owes elsewhere as (id, environment).
    delivered_to: str = ""
    owed_elsewhere: tuple[tuple[int, str], ...] = ()
    #: The item's current status was entered after this landing.
    returned_after_landing: bool = False

    @property
    def relanding_owed(self) -> bool:
        """Rework sent the landed item back before release; it must land again."""
        return self.returned_after_landing and self.status != "release"

    @property
    def delivery_wait(self) -> bool:
        """A live parked release holder waiting for enrollment or delivery.

        Tool silence is expected during this wait; only a recorded death or
        an unavailable delivery path makes the declared park actionable.
        """
        return bool(
            self.status == "release"
            and self.holder_session_id
            and self.holder_parked
            and not self.holder_native_process_gone
            and self.completion_flow_available
            and self.custody_state in {HELD, UNHELD, REMERGED}
        )

    @property
    def stranded(self) -> bool:
        """True when no release is carrying this landing to an environment."""
        return self.custody_state in ENROLLABLE_CUSTODY_STATES


def landed_without_closeout(
    conn: Any,
    *,
    project_id: int,
    now: str,
    holders: Sequence[ClaimHolder],
) -> tuple[LandedItem, ...]:
    """Items whose branch landed while the item never reached a terminal status.

    The landing stamp is the item's own ``merged_at`` or, on a merge-queue
    project, ``merge_queue_landed_at``; the earlier of the two present is the
    moment the code was on the base branch. Either stamp may come from the
    control-plane landing observer rather than from a worker that waited, so
    this row fires for a landing whose waiting process died.

    ``holders`` is the report's own :func:`claim_holders` answer, passed in
    rather than asked again. Each row carries whoever still holds the item and
    whether they are parked, because close-out is a claim-holding step: a
    landing a live session holds is that session's to finish, a parked holder
    is waiting on its delivery, and only a landing nobody holds needs a seat.
    It also carries which release holds the landing, because a holder can only
    finish a close-out the delivery has reached: an item nobody is delivering
    is a different finding from one waiting normally, and until the two were
    told apart the stranded ones were found by accident.

    Which items are even in this conversation is
    :func:`delivery_landing_custody.merged_open_items`, shared with run
    enrollment so the report and the enroller can never disagree about what
    counts as merged and still open.
    """
    records = list(merged_open_items(conn, int(project_id)))
    if not records:
        return ()
    item_ids = [int(record["id"]) for record in records]
    refs = render_item_refs(conn, item_ids)
    held_by = {holder.item_id: holder for holder in holders}
    custody = landing_custody(conn, project_id=int(project_id), item_ids=item_ids)
    flows = item_completion_flow_facts(conn, item_ids)
    marker = "%s" if db_backend.connection_is_postgres(conn) else "?"
    active_flows = {
        str(row[0])
        for row in conn.execute(
            f"SELECT id FROM deployment_flows WHERE project_id = {marker} "
            f"AND status = {marker}",
            (int(project_id), FLOW_STATUS_ACTIVE),
        ).fetchall()
    }
    returned = items_returned_after_landing(
        conn, {int(record["id"]): record for record in records}
    )
    landed = []
    for record in records:
        stamp = landed_at(record)
        if not stamp:
            continue
        item_id = int(record["id"])
        held = custody[item_id]
        holder = held_by.get(item_id)
        delivered_to = ""
        if held.state == HELD and held.run_status == RunStatus.SUCCEEDED.value:
            delivered_to = run_environment_name(conn, held.run_id) or ""
        owed = (
            owed_on_other_targets(conn, item_id, delivered_to) if delivered_to else ()
        )
        landed.append(
            LandedItem(
                item_id=item_id,
                public_ref=refs.get(item_id, str(item_id)),
                status=str(record.get("status") or ""),
                landed_at=stamp,
                landed_seconds=age_seconds(stamp, now) or 0,
                holder_session_id=holder.session_id if holder else "",
                holder_parked=bool(holder and holder.parked),
                holder_quiet_reason=holder.quiet_reason if holder else "",
                holder_idle_seconds=holder.idle_seconds if holder else 0,
                workflow_id=str(record.get("workflow_id") or ""),
                custody_state=held.state,
                custody_run_id=held.run_id,
                completion_flow_available=bool(
                    item_id in flows and flows[item_id].flow in active_flows
                ),
                holder_native_process_gone=bool(holder and holder.native_process_gone),
                holder_process_phrase=holder.process_phrase() if holder else "",
                holder_resumable=bool(holder and holder.resumable_from_transcript),
                delivered_to=delivered_to,
                owed_elsewhere=tuple((o.requirement_id, o.target) for o in owed),
                returned_after_landing=item_id in returned,
            )
        )
    return tuple(
        sorted(landed, key=lambda entry: (-entry.landed_seconds, entry.item_id))
    )


__all__ = [
    "LandedItem",
    "landed_without_closeout",
]
