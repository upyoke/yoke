"""Named outcomes shared by merge-queue readbacks and durable records."""

ENQUEUED = "enqueued"
ARMED_NOT_ENQUEUED = "armed_not_enqueued"
NEITHER = "neither"
UNREADABLE = "unreadable"
NOT_STARTED = "not_started"

IN_FLIGHT = "in_flight"
LANDED = "landed"
CLOSED_UNMERGED = "closed_unmerged"
CONFLICTED = "conflicted"
NOT_IN_FLIGHT = "not_in_flight"

ENTRY_ABSENT = "absent"
ENTRY_NOT_READ = "not_read"
ENTRY_PRESENT = "present"

MERGE_WHEN_READY_ARMED = "armed"
MERGE_WHEN_READY_CONSUMED = "consumed"
MERGE_WHEN_READY_CLEARED = "cleared"


__all__ = [
    "ARMED_NOT_ENQUEUED",
    "CLOSED_UNMERGED",
    "CONFLICTED",
    "ENQUEUED",
    "ENTRY_ABSENT",
    "ENTRY_NOT_READ",
    "ENTRY_PRESENT",
    "IN_FLIGHT",
    "LANDED",
    "MERGE_WHEN_READY_ARMED",
    "MERGE_WHEN_READY_CLEARED",
    "MERGE_WHEN_READY_CONSUMED",
    "NEITHER",
    "NOT_IN_FLIGHT",
    "NOT_STARTED",
    "UNREADABLE",
]
