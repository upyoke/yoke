"""Items whose branch landed while the item never reached a terminal status.

Landing is not finishing. A merged item still owes a close-out, and where the
project delivers through releases it owes a delivery first — so this section
exists to name the gap between "the code is on the base branch" and "the item
is done".

Three facts decide what the seat does about one row:

* **Who holds the item, and whether they are waiting.** Close-out is a
  claim-holding step, so a seat can only run it on a landing no live session
  holds — against a live holder the command is refused by name. A holder that
  is parked is waiting on the delivery its own close-out needs, and that row
  is healthy.
* **Which release holds the landing.** A row waiting on a delivery that is
  actually coming needs nothing from anybody. A row no release is carrying
  needs a release, and nothing will produce one on its own. Until these read
  differently the two were indistinguishable, and three items sat stranded for
  a day because the only way to tell them apart was a person noticing that the
  rows had not changed.
* **Which workflow the item pins.** An evidence-gated terminal transition
  refuses the bare close-out command, so a row that recommends one names the
  flags it needs.

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

from dataclasses import dataclass
from typing import Any, Sequence

from yoke_core.domain.close_out_evidence_gate import close_out_command
from yoke_core.domain.delivery_landing_custody import (
    ENROLLABLE_CUSTODY_STATES,
    HELD,
    REMERGED,
    UNDETERMINED as CUSTODY_UNDETERMINED,
    UNHELD,
    landed_at,
    landing_custody,
    merged_open_items,
)
from yoke_core.domain.item_ref_render import render_item_refs
from yoke_core.domain.steering_fleet_report_detectors import age_seconds
from yoke_core.domain.steering_fleet_report_holders import ClaimHolder


@dataclass(frozen=True)
class LandedItem:
    """One item whose branch landed while the item stayed open."""

    item_id: int
    public_ref: str
    status: str
    landed_at: str
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
    #: idle threshold means they are not driving the close-out, even if
    #: parked waiting on a delivery.
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

    @property
    def stranded(self) -> bool:
        """True when no release is carrying this landing to an environment."""
        return self.custody_state in ENROLLABLE_CUSTODY_STATES


def _holder_is_quiet(entry: LandedItem, idle_after_seconds: int | None) -> bool:
    """True when a live holder has been quiet past the report's idle threshold."""
    if not entry.holder_session_id or idle_after_seconds is None:
        return False
    return entry.holder_idle_seconds >= int(idle_after_seconds)


def holder_phrase(
    entry: LandedItem, *, idle_after_seconds: int | None = None
) -> str:
    """Who holds the item, and whether they are waiting, working, or quiet.

    A bare session id said only that somebody was there. Whether that somebody
    is parked decides whether the row needs anything at all, so the row says
    it rather than leaving a reader to go and look. A parked holder that has
    gone quiet past the idle threshold is not waiting by design — they are
    not driving the close-out, and the row has to say so.
    """
    if not entry.holder_session_id:
        return "no live holder"
    held = f"held by {entry.holder_session_id}"
    if _holder_is_quiet(entry, idle_after_seconds):
        quiet = f"quiet {entry.holder_idle_seconds // 60}m"
        parked = ", parked" if entry.holder_parked else ""
        reason = f" — {entry.holder_quiet_reason}" if entry.holder_quiet_reason else ""
        return f"{held}, {quiet}{parked}{reason}; holder is not driving this"
    if not entry.holder_parked:
        return f"{held}, working"
    return f"{held}, parked — {entry.holder_quiet_reason or 'waiting on delivery'}"


def landed_recovery(
    entry: LandedItem, *, idle_after_seconds: int | None = None
) -> str:
    """What a seat does about this row, or ``""`` when it needs nothing.

    Close-out is a claim-holding step, so a seat can only run it on a landing
    no live session holds; against a live holder the command is refused by
    name, and against a parked one there is nothing to recover from — it is
    waiting on the delivery its close-out needs. Both get silence, because a
    correct command offered for a situation that needs no command is still
    noise, and it costs every reader the time it takes to try.

    A holder quiet past the idle threshold is not that live owner. The claim
    still blocks close-out until the sweep releases it, so the row names a
    wake (the holder may yet return) and the close-out that runs once the
    claim is free.

    Where a seat can act, the command is composed for the item's own workflow.
    An evidence-gated terminal transition refuses the bare form, so the row
    names the flags rather than leaving them to be discovered through the
    denial.
    """
    command = close_out_command(entry.public_ref, workflow_id=entry.workflow_id)
    if _holder_is_quiet(entry, idle_after_seconds):
        return (
            f"wake `yoke say --item {entry.public_ref} --stdin`; "
            f"if the holder is gone, finish close-out with `{command}` "
            "once the claim is free"
        )
    if entry.holder_session_id:
        return ""
    return f"finish close-out with `{command}`; do not wait on status"


def custody_phrase(entry: LandedItem) -> str:
    """Say who is delivering this landing, in the words the seat needs.

    A stranded row has to read differently from one mid-delivery, and the two
    stranded shapes are different findings: nothing ever named the item, or
    something named it and the item has merged again since.
    """
    if entry.custody_state == HELD:
        return f"delivering in {entry.custody_run_id}"
    if entry.custody_state == REMERGED:
        return f"merged again since {entry.custody_run_id} — no release holds it"
    if entry.custody_state == CUSTODY_UNDETERMINED:
        return "release custody unreadable — no source could compare its merge"
    return "no release holds it"


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
    item_ids = [int(record["id"]) for record in records]
    refs = render_item_refs(conn, item_ids)
    held_by = {holder.item_id: holder for holder in holders}
    custody = landing_custody(conn, project_id=int(project_id), item_ids=item_ids)
    landed = []
    for record in records:
        stamp = landed_at(record)
        if not stamp:
            continue
        item_id = int(record["id"])
        held = custody[item_id]
        holder = held_by.get(item_id)
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
            )
        )
    return tuple(
        sorted(landed, key=lambda entry: (-entry.landed_seconds, entry.item_id))
    )


__all__ = [
    "LandedItem",
    "custody_phrase",
    "holder_phrase",
    "landed_recovery",
    "landed_without_closeout",
]
