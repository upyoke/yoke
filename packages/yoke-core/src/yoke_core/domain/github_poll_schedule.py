"""Read GitHub run status once a minute from the first read.

CI suites and deployment workflows can conclude at any time. All run
pollers use the same steady cadence, regardless of project or duration.
The minimum interval limits the API budget concurrent sessions share.

Run-discovery probes ask whether a dispatch has registered a run yet.
Those bounded loops stay fast because their answers move within seconds.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from yoke_contracts.designed_wait import poll_every

MINIMUM_POLL_INTERVAL_SECONDS = 60.0


@dataclass(frozen=True)
class PollSchedule:
    """The fixed interval between scheduled reads, in seconds."""

    interval_seconds: float = MINIMUM_POLL_INTERVAL_SECONDS

    def __post_init__(self) -> None:
        if self.interval_seconds < MINIMUM_POLL_INTERVAL_SECONDS:
            raise ValueError(
                f"poll interval {self.interval_seconds}s is below the "
                f"{MINIMUM_POLL_INTERVAL_SECONDS}s minimum interval"
            )

    def describe(self) -> str:
        """The cadence phrase a designed-wait announcement carries."""
        return poll_every(self.interval_seconds)


STEADY_SCHEDULE = PollSchedule()


def next_read_delay(
    elapsed_seconds: float,
    schedule: PollSchedule = STEADY_SCHEDULE,
) -> float:
    """Seconds from a completed read to the next scheduled offset.

    Measure elapsed time from the first read. A slow read consumes part of
    the interval instead of shifting every subsequent read by its cost.
    """
    steps = math.floor(elapsed_seconds / schedule.interval_seconds) + 1
    return steps * schedule.interval_seconds - elapsed_seconds


__all__ = [
    "MINIMUM_POLL_INTERVAL_SECONDS",
    "PollSchedule",
    "STEADY_SCHEDULE",
    "next_read_delay",
]
