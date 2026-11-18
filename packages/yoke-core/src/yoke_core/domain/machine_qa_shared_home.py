"""Test Machine registrations that restore the same home.

Several registrations can share a physical host and user, each with its own
name and golden. They reset the same home, so each golden is relevant when
that host and user are used.
"""

from __future__ import annotations

from typing import Any, Mapping

from yoke_core.domain.coordination_claims import active_claim
from yoke_core.domain.machine_qa_capability import host_claim_target
from yoke_core.domain.machine_qa_host_rows import (
    TestMachineRow,
    test_machine_rows,
)


def shared_home_registrations(
    conn: Any,
    settings: Mapping[str, str],
) -> list[TestMachineRow]:
    """Return every registration for the host and user in *settings*.

    A stored registration that cannot be read could name this home, so it
    raises ``TestMachineCapabilityError`` instead of being skipped.
    """
    host = settings["host"].casefold()
    return [
        row
        for row in test_machine_rows(conn)
        if row.settings["host"].casefold() == host
        and row.settings["user"] == settings["user"]
    ]


def leased_shared_home(
    conn: Any,
    rows: list[TestMachineRow],
    *,
    test_machine: str,
) -> str | None:
    """Name another registered name for this home whose lease is held now.

    The lease serializes one name. A registration of the same home under a
    different name has its own lease, so its capture can be in flight.
    """
    for row in rows:
        if row.test_machine == test_machine:
            continue
        if active_claim(conn, host_claim_target(row.test_machine)) is not None:
            return (
                f"Test Machine {row.test_machine!r} registers this host and user "
                "and is leased now, so a "
                "capture it is running could be deleted"
            )
    return None


__all__ = ["leased_shared_home", "shared_home_registrations"]
