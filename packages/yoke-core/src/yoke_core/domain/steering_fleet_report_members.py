"""Gather item facts by steering membership across execution projects."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from yoke_core.domain.steering_fleet_report_reads import FleetReportReads
from yoke_core.domain.steering_scope_membership import member_project_ids


@dataclass(frozen=True)
class SeatItemFacts:
    project_ids: tuple[int, ...]
    available: tuple[Any, ...]
    holders: tuple[Any, ...]
    undelivered: tuple[Any, ...]
    landed_open: tuple[Any, ...]
    vendor_errors: tuple[Any, ...]
    stranded: tuple[Any, ...]


def read_seat_items(
    conn: Any,
    *,
    scope: Mapping[str, Any],
    members: set[int] | None,
    session_id: str,
    now: str,
    reads: FleetReportReads,
) -> SeatItemFacts:
    """Read every execution project a document seat's members occupy."""
    owner_project = int(scope["project_id"])
    project_ids = (
        member_project_ids(conn, members)
        if scope.get("document") is not None and members is not None
        else {owner_project}
    )
    # The owning project's shared facts still feed machine and delivery rows.
    project_ids.add(owner_project)
    sources = [
        reads.project_facts(conn, project_id=project, session_id=session_id, now=now)
        for project in sorted(project_ids)
    ]

    def item_rows(name: str) -> tuple[Any, ...]:
        return tuple(
            row
            for source in sources
            for row in getattr(source, name)
            if members is None or int(row.item_id) in members
        )

    holders = item_rows("holders")
    sessions = {row.session_id for row in holders}

    def session_rows(name: str) -> tuple[Any, ...]:
        return tuple(
            row
            for source in sources
            for row in getattr(source, name)
            if members is None or row.session_id in sessions
        )

    return SeatItemFacts(
        project_ids=tuple(sorted(project_ids)),
        available=item_rows("available"),
        holders=holders,
        undelivered=session_rows("undelivered"),
        landed_open=item_rows("landed_open"),
        vendor_errors=session_rows("vendor_errors"),
        stranded=session_rows("stranded"),
    )


__all__ = ["SeatItemFacts", "read_seat_items"]
