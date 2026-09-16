"""Canonical vocabulary for the ``qa_runs.execution_status`` capture outcome.

``execution_status`` records whether a browser or agent-mission run captured
its evidence at all, which is separate from the quality verdict that evidence
later earns. The column accepts these two values or NULL.

Both the ``yoke qa run add`` / ``yoke qa run complete`` flag adapters and the
registered ``qa.run.add`` / ``qa.run.complete`` handlers read the vocabulary
from here, so an unsupported value is refused by name before it reaches the
database CHECK constraint. Schema modules restate the same two values in DDL
text because storage-layer modules may not import this one.
"""

from __future__ import annotations

from typing import Optional


CAPTURED = "captured"
CAPTURE_FAILED = "capture_failed"

#: Every value ``qa_runs.execution_status`` accepts, besides NULL.
VALID_EXECUTION_STATUSES = (CAPTURED, CAPTURE_FAILED)

#: Rendered into ``--execution-status`` usage lines.
EXECUTION_STATUS_USAGE_TOKEN = "|".join(VALID_EXECUTION_STATUSES)

EXECUTION_STATUS_HELP = (
    "Capture outcome, distinct from the quality verdict. "
    f"One of: {', '.join(VALID_EXECUTION_STATUSES)}. Omit to leave it unset."
)


def execution_status_error(value: Optional[str]) -> Optional[str]:
    """Return why ``value`` is not a storable execution status, else None.

    ``None`` is a supported input: it leaves the stored status unchanged.
    """
    if value is None or value in VALID_EXECUTION_STATUSES:
        return None
    allowed = ", ".join(VALID_EXECUTION_STATUSES)
    return (
        f"invalid execution_status {value!r} -- supported values are "
        f"{allowed}; omit the field to leave it unset"
    )


__all__ = [
    "CAPTURED",
    "CAPTURE_FAILED",
    "EXECUTION_STATUS_HELP",
    "EXECUTION_STATUS_USAGE_TOKEN",
    "VALID_EXECUTION_STATUSES",
    "execution_status_error",
]
