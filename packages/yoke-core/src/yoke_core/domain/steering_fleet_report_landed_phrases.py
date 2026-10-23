"""What a seat reads and does about one landed-but-open row.

Five facts decide what the seat does about one row:

* **What the item's own done gate still waits on.** A landing whose gate
  waits only on its active flow's next release owes nobody a command, so its
  row is one short line whatever its holder is doing; holder posture is
  context there, never the classification. An item with no deployment target
  is close-out ready, because its merge is the delivery.
* **Who holds the item, and whether they are driving it.** Close-out is a
  claim-holding step, so a seat can only run it on a landing no live session
  holds — against a live holder the command is refused by name.
* **Which release holds the landing.** A row waiting on a delivery that is
  actually coming needs nothing from anybody. A row no release is carrying
  needs a release, and nothing will produce one on its own. Until these read
  differently the two were indistinguishable, and three items sat stranded for
  a day because the only way to tell them apart was a person noticing that the
  rows had not changed.
* **Whether the landing is still the item's current work.** An item rework
  sent back from release to an earlier stage after it landed owes a new
  landing, not a close-out: its row says re-landing owed and wakes the holder
  to review and merge, because a park outside release is not a delivery wait.
* **Which workflow the item pins.** An evidence-gated terminal transition
  refuses the bare close-out command, so a row that recommends one names the
  flags it needs.
"""

from __future__ import annotations

from yoke_core.domain.close_out_evidence_gate import close_out_command
from yoke_core.domain.delivery_landing_custody import (
    HELD,
    REMERGED,
    UNDETERMINED as CUSTODY_UNDETERMINED,
)
from yoke_core.domain.steering_fleet_report_landed_gate import (
    CLOSE_OUT_READY,
    UNREADABLE,
)
from yoke_core.domain.steering_fleet_report_landed_open import LandedItem


def _holder_is_quiet(entry: LandedItem, idle_after_seconds: int | None) -> bool:
    """True when both holder silence and landing age reach the idle threshold."""
    if entry.awaiting_release or not entry.holder_session_id or idle_after_seconds is None:
        return False
    threshold = int(idle_after_seconds)
    return entry.holder_idle_seconds >= threshold and entry.landed_seconds >= threshold


def holder_phrase(entry: LandedItem, *, idle_after_seconds: int | None = None) -> str:
    """Who holds the item, and whether they are waiting, working, or quiet.

    A landing awaiting its release expects tool silence, whatever the holder. Working holders must be quiet and landed for the full
    idle threshold. A row owing a new landing says so whoever holds it.
    """
    phrase = _holder_state(entry, idle_after_seconds)
    return f"{phrase}; re-landing owed" if entry.relanding_owed else phrase


def _holder_state(entry: LandedItem, idle_after_seconds: int | None) -> str:
    if not entry.holder_session_id:
        return "no live holder"
    held = f"held by {entry.holder_session_id}"
    if entry.holder_process_phrase:
        return f"{held}, {entry.holder_process_phrase}"
    if _holder_is_quiet(entry, idle_after_seconds):
        quiet = f"quiet {entry.holder_idle_seconds // 60}m"
        parked = ", parked" if entry.holder_parked else ""
        reason = f" — {entry.holder_quiet_reason}" if entry.holder_quiet_reason else ""
        return f"{held}, {quiet}{parked}{reason}; holder is not driving this"
    if not entry.holder_parked:
        return f"{held}, working"
    waiting = "no reason given" if entry.relanding_owed else "waiting on delivery"
    return f"{held}, parked — {entry.holder_quiet_reason or waiting}"


def landed_recovery(entry: LandedItem, *, idle_after_seconds: int | None = None) -> str:
    """What a seat does about this row, or ``""`` when it needs nothing.

    A landing whose done gate waits only on its next release needs nothing
    from anybody, whoever holds it. Otherwise close-out is a claim-holding
    step, so a seat can only run it on a landing no live session holds;
    against a live holder the command is refused by name. Both get silence,
    because a correct command offered for a situation that needs no command
    is still noise, and it costs every reader the time it takes to try.

    Outside a release wait, a holder quiet for the idle threshold
    after landing is not that live owner. The claim still blocks close-out
    until the sweep releases it, so the row names a
    wake (the holder may yet return) and the close-out that runs once the
    claim is free.

    Where a seat can act, the command is composed for the item's own workflow.
    An evidence-gated terminal transition refuses the bare form, so the row
    names the flags rather than leaving them to be discovered through the
    denial.
    """
    if entry.awaiting_release:
        return ""
    if entry.relanding_owed:
        return _relanding_recovery(entry, idle_after_seconds)
    command = close_out_command(entry.public_ref, workflow_id=entry.workflow_id)
    if entry.holder_native_process_gone:
        if entry.holder_resumable:
            return f"message the holder `yoke say --item {entry.public_ref} --stdin`"
        return f"finish close-out with `{command}` once the claim is free"
    if entry.status == "release" and not entry.completion_flow_available:
        return (
            "no active completion flow; repair the item's deployment flow or "
            "project workflow delivery default, then compose its release"
        )
    if _holder_is_quiet(entry, idle_after_seconds):
        return (
            f"wake `yoke say --item {entry.public_ref} --stdin`; "
            f"if the holder is gone, finish close-out with `{command}` "
            "once the claim is free"
        )
    if entry.holder_session_id:
        return ""
    return f"finish close-out with `{command}`; do not wait on status"


def _relanding_recovery(entry: LandedItem, idle_after_seconds: int | None) -> str:
    """Wake the holder to review and merge its rework, or staff it when none."""
    ref = entry.public_ref
    holder_reachable = entry.holder_session_id and (
        entry.holder_resumable or not entry.holder_native_process_gone
    )
    if holder_reachable:
        if (
            entry.holder_parked
            or entry.holder_native_process_gone
            or (_holder_is_quiet(entry, idle_after_seconds))
        ):
            return (
                f"wake `yoke say --item {ref} --stdin` so the holder reviews and "
                "merges its rework"
            )
        return ""
    when = " once the claim is free" if entry.holder_session_id else ""
    return (
        f"claim it and re-enter its bound skill (`yoke workflows item get {ref}` "
        f"names it) to review and merge the rework{when}"
    )


def release_wait_phrase(entry: LandedItem) -> str:
    """One line for a landing awaiting its release: the flow, custody, holder.

    Which release holds it is said when one does; the holder's posture is
    context in brackets and never adds a command.
    """
    wait = f"awaiting next {entry.delivery_gate.flow} release"
    if entry.custody_state == HELD:
        wait = f"awaiting {entry.delivery_gate.flow} release — {custody_phrase(entry)}"
    elif entry.custody_state in {REMERGED, CUSTODY_UNDETERMINED}:
        wait = f"{wait} — {custody_phrase(entry)}"
    return f"{wait} ({_holder_context(entry)})"


def _holder_context(entry: LandedItem) -> str:
    if not entry.holder_session_id:
        return "no live holder"
    if entry.holder_process_phrase:
        return f"holder {entry.holder_process_phrase}"
    if entry.holder_parked:
        return "parked"
    return f"holder idle {entry.holder_idle_seconds // 60}m"


def delivery_phrase(entry: LandedItem) -> str:
    """What the gate or release says about a landing that owes close-out."""
    if entry.delivery_gate.state == CLOSE_OUT_READY:
        return "close-out ready — no deployment target, the merge is the delivery"
    if entry.delivery_gate.state == UNREADABLE:
        return f"delivery gate unreadable — {entry.delivery_gate.detail}"
    return custody_phrase(entry)


def custody_phrase(entry: LandedItem) -> str:
    """Say who is delivering this landing, in the words the seat needs.

    A stranded row has to read differently from one mid-delivery, and the two
    stranded shapes are different findings: nothing ever named the item, or
    something named it and the item has merged again since. A succeeded run
    has already delivered, so its row names where and what remains owed.
    """
    if entry.custody_state == HELD and entry.delivered_to:
        owed = ", ".join(
            f"#{requirement_id} on {target or 'unspecified target'}"
            for requirement_id, target in entry.owed_elsewhere
        )
        delivered = f"delivered to {entry.delivered_to}"
        return f"{delivered}; owes {owed}" if owed else delivered
    if entry.custody_state == HELD:
        return f"delivering in {entry.custody_run_id}"
    if entry.custody_state == REMERGED:
        return f"merged again since {entry.custody_run_id} — no release holds it"
    if entry.custody_state == CUSTODY_UNDETERMINED:
        return "release custody unreadable — no source could compare its merge"
    return "no release holds it"


__all__ = [
    "custody_phrase",
    "delivery_phrase",
    "holder_phrase",
    "landed_recovery",
    "release_wait_phrase",
]
