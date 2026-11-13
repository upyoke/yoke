"""What one control-plane observation of a queued landing means.

The durable handoff route exits the merge command and leaves the wait to
the relay's observer, so whatever the observer declines to notice is
silence to the holder. Reading only ``merged`` is therefore not enough:
a pull request GitHub stops driving — because the base moved underneath
it and it went dirty, because it was closed, because its arming was
cleared without a merge, because one of its own required checks has
concluded red, or its queue entry is UNMERGEABLE — will never report merged,
and its holder waits for a
notification that cannot arrive.

What it must not do is mistake the ordinary wait for that. GitHub creates
the queue entry only once the pull request's own required checks pass, so
an armed, eligible pull request whose checks are still running is a
landing in progress. The observation reads the same four fields the
admission check reads — armed, queued, eligible, entry-gated — and
reports a stop when admission is lost, including a retained UNMERGEABLE entry.
An open pull request whose merge state GitHub reports unknown is not a stop:
GitHub reports that mid-merge, after it clears the entry and the arming.
An open CLEAN pull request with neither arming nor a queue entry, and an
armed one GitHub could queue now but holds no entry for, is read again after
three seconds before it can be reported as stopped. Arming alone does not
queue a ready pull request, so the second case stops until `yoke merge item`
enqueues it directly.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Callable

from yoke_core.domain.merge_queue_enqueue_verification import LandingReadback
from yoke_core.domain.merge_queue_landing_notice import HOLDER


# What the queued pull request turned out to be doing.
LANDED = "landed"
EJECTED = "ejected"
WAITING = "waiting"


@dataclass(frozen=True)
class LandingObservation:
    """One reading of a pending landing, with the facts behind it."""

    kind: str
    recovery: str = ""
    observed: str = ""


def confirm_clean_landing(
    readback: LandingReadback,
    reread: Callable[[], LandingReadback],
) -> LandingReadback:
    """Re-read a possible CLEAN mid-merge or entry-forming once before an ejection.

    GitHub can clear arming and queue membership seconds before recording
    the merge, and can form an armed pull request's entry seconds after its
    checks pass. Use the second read for both the durable record and notice;
    a persistent CLEAN absence is still a stop, with no stored retry state.
    """
    state, member = readback.state, readback.membership
    if (
        state is not None
        and not state.merged
        and not state.closed
        and (
            readback.armed_ready()
            or (
                not state.auto_merge_active
                and state.merge_state_status.strip().lower() == "clean"
            )
        )
        and member is not None
        and not member.in_queue
        and member.mergeable != "CONFLICTING"
        and not readback.failed_required
        and readback.queue_recovery.get("action") != "held"
    ):
        time.sleep(3.0)
        return reread()
    return readback


def classify_pending_landing(
    readback: LandingReadback,
    *,
    target: str,
) -> LandingObservation:
    """Decide whether a pending landing merged, was dropped, or is running.

    An unreadable pull request or an unreadable membership cannot prove an
    ejection, so both stay ``WAITING`` — the next poll asks again. So does
    a pull request GitHub is still holding, whether it has reached the
    queue yet or is armed and waiting for its own checks, and so does an
    open pull request whose merge state GitHub reports unknown: GitHub
    reports that while it recomputes, including mid-merge after it clears
    the queue entry and merge-when-ready, and so does an UNMERGEABLE entry
    whose mergeability GitHub has not decided and whose current train has not
    failed. A decided UNMERGEABLE entry
    is an ejection even before GitHub removes it from the queue.
    """
    if readback.state is None:
        return LandingObservation(WAITING)
    if readback.merged:
        return LandingObservation(LANDED)
    if readback.queue_recovery.get("action") == "held":
        return LandingObservation(WAITING)
    if readback.membership is None:
        return LandingObservation(WAITING)
    if readback.admitted() or readback.undetermined():
        return LandingObservation(WAITING)
    return LandingObservation(
        EJECTED,
        recovery=readback.recovery(target=target),
        observed=(
            f"{readback.describe()}, "
            f"state={'closed' if readback.state.closed else 'open'}"
        ),
    )


def ejection_message(
    public_ref: str,
    pr_number: str,
    observation: LandingObservation,
    route: str,
    disarm_note: str,
) -> str:
    """Tell the holder its landing is over and what to do about it."""
    head = (
        f"Landing stopped for {public_ref} (pull request #{pr_number}): "
        f"GitHub is no longer going to land it"
    )
    tail = (
        f"Observed {observation.observed}. If the queue merged it in the "
        "meantime, re-running `yoke merge item` converges on that merge "
        "instead. Follow the named recovery before re-entering that command."
    )
    if disarm_note:
        tail = f"{disarm_note}. {tail}"
    if route == HOLDER:
        return f"{head} — {observation.recovery}. {tail}"
    return (
        f"{head}, and its claim holder is gone. Route normal "
        f"starvation/restaffing so the lane can be recovered: "
        f"{observation.recovery}. {tail}"
    )


__all__ = [
    "EJECTED",
    "LANDED",
    "WAITING",
    "LandingObservation",
    "classify_pending_landing",
    "confirm_clean_landing",
    "ejection_message",
]
