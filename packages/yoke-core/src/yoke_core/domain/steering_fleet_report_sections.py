"""Which section of the report names a holder, and under what heading.

The claim inventory and the holder alarms render the same row shape, and an
empty section prints nothing at all, so an inventory that listed every holder
printed a byte-identical row directly beneath the alarm that had just named
it. A seat read one quiet holder as two sessions in trouble, and read the
inventory's below-threshold rows as more rows under a heading promising no
tool call in over twenty minutes.

So a holder appears exactly once, in the most specific section that claims
it, and what is left over prints under a heading that says quiet there is
not an alarm.
"""

from __future__ import annotations

from yoke_core.domain.steering_fleet_report import ClaimHolder, FleetReport

#: Heading for the leftover inventory. It says what the section is not,
#: because every row beneath it is a holder no alarm above claimed.
CLAIMS_HEADING = "live item claims — every other holder; quiet here is no alarm"


def unlisted_holders(report: FleetReport) -> tuple[ClaimHolder, ...]:
    """Holders no alarm section already named, so no row is printed twice."""
    named = {h.session_id for h in report.idle}
    named.update(h.session_id for h in report.suspected_orphaned_waiters)
    named.update(call.session_id for call in report.in_flight)
    return tuple(h for h in report.holders if h.session_id not in named)


__all__ = ["CLAIMS_HEADING", "unlisted_holders"]
