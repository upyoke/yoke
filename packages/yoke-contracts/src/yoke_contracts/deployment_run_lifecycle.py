"""The deployment-run status vocabulary, and which of those states are final.

One home for the statuses ``deployment_runs.status`` accepts, because several
readers ask the same two questions about a run: is it still going, and is it
over? A reader that spelled either set inline drifts from the column's own
constraint the moment a status is added there.

Membership is an allowlist in both directions on purpose. A status this build
does not recognise is neither open nor terminal, so a caller deciding whether
to release a run's resources refuses on the unknown value instead of reading
"not open" as "finished" and reclaiming something a newer build still uses.
"""

from __future__ import annotations

RUN_STATUS_CREATED = "created"
RUN_STATUS_EXECUTING = "executing"
RUN_STATUS_SUCCEEDED = "succeeded"
RUN_STATUS_FAILED = "failed"
RUN_STATUS_CANCELLED = "cancelled"

# A run that has not reached a verdict yet; its resources are still in use.
OPEN_RUN_STATUSES: tuple[str, ...] = (
    RUN_STATUS_CREATED,
    RUN_STATUS_EXECUTING,
)
# A run that has reached a verdict; nothing will read its execution state again.
TERMINAL_RUN_STATUSES: tuple[str, ...] = (
    RUN_STATUS_SUCCEEDED,
    RUN_STATUS_FAILED,
    RUN_STATUS_CANCELLED,
)
DEPLOYMENT_RUN_STATUSES: tuple[str, ...] = OPEN_RUN_STATUSES + TERMINAL_RUN_STATUSES


def run_is_terminal(status: str) -> bool:
    """Whether *status* names a final run state, by allowlist."""
    return str(status).strip() in TERMINAL_RUN_STATUSES


def run_is_open(status: str) -> bool:
    """Whether *status* names a run still on its way to a verdict."""
    return str(status).strip() in OPEN_RUN_STATUSES


__all__ = [
    "DEPLOYMENT_RUN_STATUSES",
    "OPEN_RUN_STATUSES",
    "RUN_STATUS_CANCELLED",
    "RUN_STATUS_CREATED",
    "RUN_STATUS_EXECUTING",
    "RUN_STATUS_FAILED",
    "RUN_STATUS_SUCCEEDED",
    "TERMINAL_RUN_STATUSES",
    "run_is_open",
    "run_is_terminal",
]
