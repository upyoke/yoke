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
RESUME_NEVER_STARTED_RESULT = "resume_never_started"
RESUME_RUNAWAY_RESULT = "resume_runaway"

RESUME_TERMINAL_RESULTS = frozenset(
    {
        RESUMED_COMPLETED_RESULT,
        RESUMED_DIED_RESULT,
        RESUME_NEVER_STARTED_RESULT,
        RESUME_RUNAWAY_RESULT,
    }
)
RESUME_RESULT_CODES = frozenset({RESUMED_RUNNING_RESULT, *RESUME_TERMINAL_RESULTS})


def resume_roster_state(result_code: object) -> str | None:
    """Project one stored attempt result onto the compact roster vocabulary."""
    if result_code == RESUMED_RUNNING_RESULT:
        return "resumed-running"
    if result_code == RESUMED_COMPLETED_RESULT:
        return "resumed-completed"
    if result_code in RESUME_TERMINAL_RESULTS:
        return "resumed-died"
    return None


__all__ = [
    "RESUME_ATTEMPT_ENV",
    "RESUME_INACTIVITY_SECONDS",
    "RESUME_NEVER_STARTED_RESULT",
    "RESUME_RESULT_CODES",
    "RESUME_RUNAWAY_RESULT",
    "RESUME_RUNAWAY_SECONDS",
    "RESUME_TERMINAL_RESULTS",
    "RESUMED_COMPLETED_RESULT",
    "RESUMED_DIED_RESULT",
    "RESUMED_RUNNING_RESULT",
    "resume_roster_state",
]
