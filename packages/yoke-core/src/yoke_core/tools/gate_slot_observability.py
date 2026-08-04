"""What the shared cluster can tell you about who holds a gate slot.

Admission arbitrates through advisory locks, which say only "taken" or
"free". These helpers put a name on each arbitrating connection via
``application_name`` and read it back out of ``pg_stat_activity``, so a
queued gate can report who it is waiting behind and how deep the queue is
rather than only that it is waiting. Nothing here decides anything: the
arbitration loop lives in :mod:`yoke_core.tools.gate_admission`.

Every read degrades to an empty answer rather than failing the gate —
observability must never be the reason a test run dies.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Sequence


#: ``application_name`` prefixes for the two admission states a connection
#: can be in. Distinct prefixes let one query separate holders from waiters.
SLOT_HELD_APP_PREFIX = "yoke-gate-held:"
SLOT_WAIT_APP_PREFIX = "yoke-gate-wait:"


def slot_identity() -> str:
    """Name this invocation for the shared cluster's activity view.

    The working directory is the useful half — on a fleet of worktrees it
    is what tells one queued gate from another — and the pid disambiguates
    two runs in the same tree.
    """
    try:
        tree = Path.cwd().name or "unknown"
    except OSError:
        tree = "unknown"
    return f"{tree}/pid{os.getpid()}"


def _stamp_activity(conn, prefix: str, identity: str) -> None:
    """Publish this connection's admission state; never fail the gate.

    ``set_config`` rather than ``SET`` because the value is a parameter —
    the identity carries a directory name this module does not control.
    """
    try:
        conn.execute(
            "SELECT set_config('application_name', %s, false)",
            (f"{prefix}{identity}",),
        )
    except Exception:
        pass


def slot_parties(conn) -> tuple[list[str], list[str]]:
    """Return ``(holder identities, waiter identities)`` from the cluster."""
    try:
        rows = conn.execute(
            "SELECT application_name FROM pg_stat_activity "
            "WHERE application_name LIKE %s OR application_name LIKE %s",
            (f"{SLOT_HELD_APP_PREFIX}%", f"{SLOT_WAIT_APP_PREFIX}%"),
        ).fetchall()
    except Exception:
        return ([], [])
    names = [str(row[0]) for row in rows]
    holders = [
        name[len(SLOT_HELD_APP_PREFIX):]
        for name in names
        if name.startswith(SLOT_HELD_APP_PREFIX)
    ]
    waiters = [
        name[len(SLOT_WAIT_APP_PREFIX):]
        for name in names
        if name.startswith(SLOT_WAIT_APP_PREFIX)
    ]
    return (sorted(holders), sorted(waiters))


def slot_occupancy(conn) -> tuple[list[str], int]:
    """Return ``(holder identities, waiting connection count)``."""
    holders, waiters = slot_parties(conn)
    return (holders, len(waiters))


def waiting_announcement(
    cap: int, waited_seconds: float, holders: Sequence[str], waiting: int,
) -> str:
    """Say who holds the slot and how deep the queue is, not just that we wait."""
    who = ", ".join(holders) if holders else "a run that did not name itself"
    # This connection is itself one of the waiters in the view.
    ahead = max(0, waiting - 1)
    queue = f"; {ahead} other queued run(s)" if ahead else ""
    return (
        f"gate admission: {cap} heavy gate slot(s) held by {who}{queue}; "
        f"waiting ({waited_seconds:.0f}s so far)"
    )


__all__ = [
    "SLOT_HELD_APP_PREFIX",
    "SLOT_WAIT_APP_PREFIX",
    "slot_identity",
    "slot_occupancy",
    "slot_parties",
    "waiting_announcement",
]
