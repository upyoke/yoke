"""Shared lifecycle vocabulary for detached native-session resumes."""

from __future__ import annotations


RESUME_ATTEMPT_ENV = "YOKE_HEADLESS_RESUME_ATTEMPT_ID"

# A resume may legitimately spend several minutes reasoning without a tool
# hook. Custody therefore reacts only to a sustained quiet window, while the
# absolute ceiling remains a separate last-resort runaway guard.
RESUME_INACTIVITY_SECONDS = 20 * 60
RESUME_RUNAWAY_SECONDS = 60 * 60

RESUMED_RUNNING_RESULT = "resumed_running"
RESUMED_COMPLETED_RESULT = "resumed_completed"
RESUMED_DIED_RESULT = "resumed_died"
RESUME_EXITED_NONZERO_RESULT = "resume_exited_nonzero"
RESUME_NEVER_STARTED_RESULT = "resume_never_started"
RESUME_RUNAWAY_RESULT = "resume_runaway"

# A resume that failed outright. ``resumed_completed`` is deliberately not
# here: a resume process exiting cleanly says the turn is over, not that the
# envelope arrived, so it leaves the attempt open for the delivery verdict in
# ``wake_delivery`` to close.
RESUME_TERMINAL_RESULTS = frozenset(
    {
        RESUMED_DIED_RESULT,
        RESUME_EXITED_NONZERO_RESULT,
        RESUME_NEVER_STARTED_RESULT,
        RESUME_RUNAWAY_RESULT,
    }
)
# What the machine that started a resume can observe about it directly: the
# native exited cleanly, exited with a failure, or vanished without leaving an
# outcome behind. The remaining terminal results are inferred from session
# activity by the control plane, and no relay ever reports them.
RESUME_RELAY_SETTLEMENT_RESULTS = frozenset(
    {
        RESUMED_COMPLETED_RESULT,
        RESUMED_DIED_RESULT,
        RESUME_EXITED_NONZERO_RESULT,
    }
)
RESUME_RESULT_CODES = frozenset(
    {RESUMED_RUNNING_RESULT, RESUMED_COMPLETED_RESULT, *RESUME_TERMINAL_RESULTS}
)


def resume_roster_state(result_code: object) -> str | None:
    """Project one stored attempt result onto the compact roster vocabulary."""
    if result_code in {RESUMED_RUNNING_RESULT, RESUMED_COMPLETED_RESULT}:
        # Both mean the resume happened and the delivery verdict has not
        # landed yet, which the roster reads as still resuming.
        return "resumed-running"
    if result_code in RESUME_TERMINAL_RESULTS:
        return "resumed-died"
    return None


__all__ = [
    "RESUME_ATTEMPT_ENV",
    "RESUME_EXITED_NONZERO_RESULT",
    "RESUME_INACTIVITY_SECONDS",
    "RESUME_NEVER_STARTED_RESULT",
    "RESUME_RELAY_SETTLEMENT_RESULTS",
    "RESUME_RESULT_CODES",
    "RESUME_RUNAWAY_RESULT",
    "RESUME_RUNAWAY_SECONDS",
    "RESUME_TERMINAL_RESULTS",
    "RESUMED_COMPLETED_RESULT",
    "RESUMED_DIED_RESULT",
    "RESUMED_RUNNING_RESULT",
    "resume_roster_state",
]
