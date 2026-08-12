"""When to read a run's status, given how that run can conclude.

Polling costs a GitHub API call whether or not the answer changed, and the
runs Yoke waits on have a known shape: the full CI suite finishes on a hard
floor near ten minutes, while the ways it fails early — a contract job that
concludes in under a minute and skips the shard matrix, a queue ejection, a
wedged queue entry — all show inside the first few minutes. Between those
two regions the status is simply not able to move, so every read taken
there buys nothing and spends budget that concurrent sessions share.

A schedule is therefore three regions rather than one interval: front-loaded
probes that catch the whole fast-failure class, a quiet window with no reads
at all, and a steady tail from the point where the run can start concluding.
A run without a known duration floor gets the tail alone, which is the same
schedule with no probes and no quiet window.

One rule holds across every region and every caller: no two reads of the
same run are closer together than :data:`MINIMUM_POLL_INTERVAL_SECONDS`.
:class:`PollSchedule` refuses to exist when its own offsets would break
that, so the floor is a property of the schedule rather than a convention
each poll loop is trusted to keep.

What this does not cover is a probe for something that has not started
yet — whether a dispatch has registered a run, whether a re-posted
dispatch took. Those answers do move within seconds, and the loops asking
them are bounded at a handful of reads, so they stay fast on purpose.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

#: No question about a run is worth asking more often than this. Twenty
#: concurrent sessions polling faster than this consume most of an hourly
#: GitHub budget between them before any other call is counted.
MINIMUM_POLL_INTERVAL_SECONDS = 60.0


@dataclass(frozen=True)
class PollSchedule:
    """The offsets, in seconds from the first read, at which to read again.

    ``probe_offsets`` are the front-loaded reads; ``quiet_until_seconds``
    is the first offset the tail may use, so nothing is read between the
    last probe and it; ``interval_seconds`` is the tail cadence from there
    on. Defaults describe a run with no known duration floor: no probes, no
    quiet window, one read a minute.
    """

    probe_offsets: tuple[float, ...] = ()
    quiet_until_seconds: float = 0.0
    interval_seconds: float = MINIMUM_POLL_INTERVAL_SECONDS

    def __post_init__(self) -> None:
        previous = 0.0
        for offset in self.probe_offsets:
            if offset - previous < MINIMUM_POLL_INTERVAL_SECONDS:
                raise ValueError(
                    f"poll offset {offset}s follows {previous}s by less than "
                    f"the {MINIMUM_POLL_INTERVAL_SECONDS}s minimum interval"
                )
            previous = offset
        if (
            self.quiet_until_seconds
            and self.quiet_until_seconds - previous
            < MINIMUM_POLL_INTERVAL_SECONDS
        ):
            raise ValueError(
                f"quiet window ending at {self.quiet_until_seconds}s follows "
                f"{previous}s by less than the "
                f"{MINIMUM_POLL_INTERVAL_SECONDS}s minimum interval"
            )
        if self.interval_seconds < MINIMUM_POLL_INTERVAL_SECONDS:
            raise ValueError(
                f"poll interval {self.interval_seconds}s is below the "
                f"{MINIMUM_POLL_INTERVAL_SECONDS}s minimum interval"
            )


#: For a run of the project's full CI suite. The probes cover the fast
#: failures, the quiet window covers the stretch where a suite on a
#: ten-minute floor cannot yet have concluded, and the tail picks the
#: verdict up within a minute of it existing.
CI_SUITE_SCHEDULE = PollSchedule(
    probe_offsets=(60.0, 120.0, 180.0),
    quiet_until_seconds=480.0,
)

#: For a run with no known duration floor — a deploy stage, an arbitrary
#: workflow waited on by run id. It can conclude at any moment, so the only
#: thing to apply is the floor itself.
STEADY_SCHEDULE = PollSchedule()


def next_read_delay(
    elapsed_seconds: float, schedule: PollSchedule = STEADY_SCHEDULE,
) -> float:
    """Seconds to wait before the next read, from a read just taken.

    ``elapsed_seconds`` is measured from the poll loop's first read. The
    delay lands on the schedule's next offset rather than adding a fixed
    interval to now, so a slow read is absorbed by the schedule instead of
    pushing every later read back by the time it cost.
    """
    for offset in schedule.probe_offsets:
        if offset > elapsed_seconds:
            return offset - elapsed_seconds
    if schedule.quiet_until_seconds > elapsed_seconds:
        return schedule.quiet_until_seconds - elapsed_seconds
    tail_elapsed = elapsed_seconds - schedule.quiet_until_seconds
    steps = math.floor(tail_elapsed / schedule.interval_seconds) + 1
    return (
        schedule.quiet_until_seconds
        + steps * schedule.interval_seconds
        - elapsed_seconds
    )


__all__ = [
    "CI_SUITE_SCHEDULE",
    "MINIMUM_POLL_INTERVAL_SECONDS",
    "PollSchedule",
    "STEADY_SCHEDULE",
    "next_read_delay",
]
