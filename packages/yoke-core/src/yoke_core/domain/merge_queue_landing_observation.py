"""What one control-plane observation of a queued landing means.

The durable handoff route exits the merge command and leaves the wait to
the relay's observer, so whatever the observer declines to notice is
silence to the holder. Reading only ``merged`` is therefore not enough:
a pull request GitHub stops driving — because the base moved underneath
it and it went dirty, because it was closed, because its arming was
cleared without a merge, because one of its own required checks has
concluded red — will never report merged, and its holder waits for a
notification that cannot arrive.

What it must not do is mistake the ordinary wait for that. GitHub creates
the queue entry only once the pull request's own required checks pass, so
an armed, eligible pull request whose checks are still running is a
landing in progress. The observation reads the same four fields the
admission check reads — armed, queued, eligible, entry-gated — and
reaches the holder only when GitHub is holding none of them.
"""

from __future__ import annotations

from dataclasses import dataclass

from yoke_core.domain.merge_queue_enqueue_verification import LandingReadback


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


def classify_pending_landing(
    readback: LandingReadback,
    *,
    target: str,
) -> LandingObservation:
    """Decide whether a pending landing merged, was dropped, or is running.

    An unreadable pull request or an unreadable membership cannot prove an
    ejection, so both stay ``WAITING`` — the next poll asks again. So does
    a pull request GitHub is still holding, whether it has reached the
    queue yet or is armed and waiting for its own checks.
    """
    if readback.state is None:
        return LandingObservation(WAITING)
    if readback.merged:
        return LandingObservation(LANDED)
    if readback.membership is None:
        return LandingObservation(WAITING)
    if readback.admitted():
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
) -> str:
    """Tell the holder its landing is over and what to do about it."""
    head = (
        f"Landing stopped for {public_ref} (pull request #{pr_number}): "
        f"GitHub is no longer going to land it"
    )
    tail = (
        f"Observed {observation.observed}. If the queue merged it in the "
        "meantime, re-running `yoke merge item` converges on that merge "
        "instead."
    )
    if route == "holder":
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
    "ejection_message",
]
