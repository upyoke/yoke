"""Help descriptions for launch operations whose outcome needs explaining."""

from __future__ import annotations


LAUNCH_CANCEL_DESCRIPTION = (
    "Cancel one session launch. A launch whose session has registered but "
    "not yet received its instructions ends that session too: it is "
    "terminated, its claims released, and one native-process reap queued. "
    "A launch whose instructions were already delivered is refused as "
    "launch_session_working, because that session may be working; end it "
    'deliberately with `yoke sessions terminate SESSION-ID --reason "<why>"`. '
    "A failed unregistered launch with recorded native exit evidence is settled "
    "by cancel and leaves the steering report; its diagnostic evidence is retained. "
    "A launch whose native process exists but has no recorded exit moves to "
    "outcome_unknown (cancellation_requires_reconciliation); resolve it with "
    "`yoke session-control launch reconcile LAUNCH-ID`. A cancelled launch is "
    "final: reconcile never revives it."
)

#: Operation name -> help description, where the usage line alone is not enough.
LAUNCH_DESCRIPTIONS = {"cancel": LAUNCH_CANCEL_DESCRIPTION}

__all__ = ["LAUNCH_CANCEL_DESCRIPTION", "LAUNCH_DESCRIPTIONS"]
