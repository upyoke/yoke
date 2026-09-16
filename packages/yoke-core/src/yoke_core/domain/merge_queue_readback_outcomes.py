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

# How an attempt to hold a candidate — clear its arming and remove its queue
# entry — actually ended, read back rather than inferred from the mutations.
HOLD_HELD = "held"
HOLD_ALREADY_CLEAR = "already_clear"
HOLD_ALREADY_LANDED = "already_landed"
HOLD_LANDED_DURING_HOLD = "landed_during_hold"
HOLD_NOT_HELD = "not_held"
HOLD_UNVERIFIED = "unverified"
#: The hold never reached GitHub: undoing an arming a person created needs
#: that person's authorization, and this process has none bound.
HOLD_USER_AUTHORITY_REQUIRED = "user_authority_required"


__all__ = [
    "ARMED_NOT_ENQUEUED",
    "CLOSED_UNMERGED",
    "CONFLICTED",
    "ENQUEUED",
    "ENTRY_ABSENT",
    "ENTRY_NOT_READ",
    "ENTRY_PRESENT",
    "HOLD_ALREADY_CLEAR",
    "HOLD_ALREADY_LANDED",
    "HOLD_HELD",
    "HOLD_LANDED_DURING_HOLD",
    "HOLD_NOT_HELD",
    "HOLD_UNVERIFIED",
    "HOLD_USER_AUTHORITY_REQUIRED",
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
