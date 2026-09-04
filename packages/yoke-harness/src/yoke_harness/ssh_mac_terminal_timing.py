"""How long the Terminal bridge waits, sized by what the host is doing.

A fixed wait is a guess about a machine the code cannot see. On an idle Mac a
new window is frontmost in a fraction of a second and its output appears
immediately; on the same Mac under a load average of five, both take several
seconds, and a wait tuned for the idle case expires while the machine is
merely busy. That failure reads as a missing privacy grant, which is how one
bridge failure was diagnosed as permissions for a day.

So the waits scale with the host's own load average, which the bridge already
has to read, and every wait is reported alongside the load that sized it, so a
timeout is legible as "this long, at this load" rather than as a bare timeout.
"""

from __future__ import annotations


#: The wait an unloaded host gets before its new window must be frontmost.
FOCUS_WAIT_BASE_SECONDS = 5.0
#: The wait an unloaded host gets before typed text must appear in the window.
TRANSCRIPT_WAIT_BASE_SECONDS = 5.0
#: The ceiling on any load-scaled wait. A host slow enough to need more than
#: this is not slow, it is stuck, and the operation should say so and stop.
LOAD_SCALED_WAIT_CAP_SECONDS = 45.0
#: How often a wait re-asks. Each poll is one SSH round trip, so this is a
#: floor on politeness rather than a resolution the answer actually has.
BRIDGE_POLL_SECONDS = 0.25


def load_scaled_wait(base_seconds: float, load_average: float | None) -> float:
    """Return *base_seconds* stretched by the host's load, within the cap.

    An unreadable load average scales nothing: guessing a busy host from a
    failed probe would hide the probe's own failure behind a longer wait.
    """
    load = max(0.0, float(load_average or 0.0))
    return min(LOAD_SCALED_WAIT_CAP_SECONDS, float(base_seconds) * (1.0 + load))


__all__ = [
    "BRIDGE_POLL_SECONDS",
    "FOCUS_WAIT_BASE_SECONDS",
    "LOAD_SCALED_WAIT_CAP_SECONDS",
    "TRANSCRIPT_WAIT_BASE_SECONDS",
    "load_scaled_wait",
]
