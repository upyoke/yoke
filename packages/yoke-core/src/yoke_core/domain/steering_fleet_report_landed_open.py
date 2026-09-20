"""Items whose branch landed while the item never reached a terminal status.

Landing is not finishing. A merged item still owes a close-out, and where the
project delivers through releases it owes a delivery first — so this section
exists to name the gap between "the code is on the base branch" and "the item
is done".

Two facts decide what the seat does about one row, and the section used to
carry only the first:

* **Who holds the item.** Close-out is a claim-holding step, so a landing with
  a live holder is a message away from finished and one with none needs
  staffing.
* **Which release holds the landing.** A row waiting on a delivery that is
  actually coming needs nothing from anybody. A row no release is carrying
  needs a release, and nothing will produce one on its own. Until these read
  differently the two were indistinguishable, and three items sat stranded for
  a day because the only way to tell them apart was a person noticing that the
  rows had not changed.

The custody answer comes from :mod:`delivery_landing_custody`, which run
enrollment reads too. That sharing is the point: what the report calls
stranded is exactly what the next release start will enroll, so the seat is
never told to chase something the product was about to do by itself.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Sequence

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
from yoke_core.domain.steering_fleet_report_detectors import age_seconds, marker
from yoke_core.domain.work_claim_targets import scope_int_sql


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
    #: a landing someone can be told to finish and one that needs staffing.
    holder_session_id: str = ""
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




def landed_recovery(public_ref: str) -> str:
    """The close-out recipe both the text and the machine projection print."""
    return (
        f"finish close-out with `yoke merge item {public_ref}`; do not wait on status"
    )


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


def _live_item_holders(conn: Any, item_ids: Sequence[int]) -> dict[int, str]:
    """Which of ``item_ids`` a live session still holds the claim on.

    Only sessions that have neither ended nor terminated count: an ended
    session cannot be asked to run close-out, so reporting it as the holder
    would name a recovery path that does not exist.
    """
    if not item_ids:
        return {}
    p = marker(conn)
    scope = scope_int_sql(conn, "wc.scope", "item_id")
    holes = ", ".join(p for _ in item_ids)
    rows = conn.execute(
        f"""SELECT {scope} AS item_id, wc.session_id
              FROM work_claims wc
              JOIN harness_sessions hs ON hs.session_id = wc.session_id
             WHERE wc.target_kind = 'item'
               AND wc.released_at IS NULL
               AND hs.ended_at IS NULL
               AND hs.terminated_at IS NULL
               AND {scope} IN ({holes})
             ORDER BY wc.id""",
        tuple(int(value) for value in item_ids),
    ).fetchall()
    return {int(row[0]): str(row[1]) for row in rows}


def landed_without_closeout(
    conn: Any,
    *,
    project_id: int,
    now: str,
) -> tuple[LandedItem, ...]:
    """Items whose branch landed while the item never reached a terminal status.

    The landing stamp is the item's own ``merged_at`` or, on a merge-queue
    project, ``merge_queue_landed_at``; the earlier of the two present is the
    moment the code was on the base branch. Either stamp may come from the
    control-plane landing observer rather than from a worker that waited, so
    this row fires for a landing whose waiting process died.

    Each row carries whoever still holds the item, because close-out is a
    claim-holding step: a landing with a live holder is a message away from
    finished, and one with none needs a seat. It also carries which release
    holds the landing, because a holder can only finish a close-out the
    delivery has reached: an item nobody is delivering is a different
    finding from one waiting normally, and until the two were told apart the
    stranded ones were found by accident.

    Which items are even in this conversation is
    :func:`delivery_landing_custody.merged_open_items`, shared with run
    enrollment so the report and the enroller can never disagree about what
    counts as merged and still open.
    """
    records = list(merged_open_items(conn, int(project_id)))
    item_ids = [int(record["id"]) for record in records]
    refs = render_item_refs(conn, item_ids)
    holders = _live_item_holders(conn, item_ids)
    custody = landing_custody(conn, project_id=int(project_id), item_ids=item_ids)
    landed = []
    for record in records:
        stamp = landed_at(record)
        if not stamp:
            continue
        item_id = int(record["id"])
        held = custody[item_id]
        landed.append(
            LandedItem(
                item_id=item_id,
                public_ref=refs.get(item_id, str(item_id)),
                status=str(record.get("status") or ""),
                landed_at=stamp,
                landed_seconds=age_seconds(stamp, now) or 0,
                holder_session_id=holders.get(item_id, ""),
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
    "landed_recovery",
    "landed_without_closeout",
]
