"""Test Machine registrations that restore the same home.

Several projects can register one physical host and user, each under its own
name and with its own golden. Every one of them resets the same home, so golden
custody follows the host and user, never the registered name.
"""

from __future__ import annotations

from typing import Any, Mapping

from yoke_core.domain.coordination_claims import active_claim
from yoke_core.domain.machine_qa_capability import host_claim_target
from yoke_core.domain.machine_qa_capability_rows import (
    TestMachineCapabilityRow,
    test_machine_capability_rows,
)


def shared_home_registrations(
    conn: Any,
    settings: Mapping[str, str],
) -> list[TestMachineCapabilityRow]:
    """Return every project's registration of the host and user in *settings*.

    A stored registration that cannot be read could name this home, so it
    raises ``TestMachineCapabilityError`` instead of being skipped.
    """
    host = settings["host"].casefold()
    return [
        row
        for row in test_machine_capability_rows(conn)
        if row.settings["host"].casefold() == host
        and row.settings["user"] == settings["user"]
    ]


def leased_shared_home(
    conn: Any,
    rows: list[TestMachineCapabilityRow],
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
                f"project {row.project!r} registers this host and user as "
                f"{row.test_machine!r}, and that machine is leased now, so a "
                "capture it is running could be deleted"
            )
    return None


__all__ = ["leased_shared_home", "shared_home_registrations"]
