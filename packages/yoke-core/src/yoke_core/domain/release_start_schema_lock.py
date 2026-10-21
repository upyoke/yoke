"""One release driver at a time applies the additive schema to a database.

``CREATE ... IF NOT EXISTS`` is not safe under concurrency in Postgres: two
drivers both pass the existence check and the second insert into ``pg_type``
fails. Every run on one control plane converges the same database, so a stage
and a production run started together raced on 2026-10-21 and one crashed.

A driver therefore holds a session-level advisory lock on one fixed key for
the whole converge, which commits table by table. The second driver waits,
then finds every object present. Its connection names its run in
``application_name`` so a driver that waits past :data:`LOCK_WAIT_SECONDS`
can refuse naming the run that holds the lock.
"""

from __future__ import annotations

import hashlib
import time
from contextlib import contextmanager
from typing import Any, Iterator

#: Advisory-lock id serializing release-start convergence on one database.
#: Postgres advisory locks carry the database in their lock tag, so one
#: constant gives per-database exclusion.
LOCK_KEY = int.from_bytes(
    hashlib.sha256(b"yoke.release_start.schema_converge").digest()[:8],
    "big",
    signed=True,
)

#: How long a driver waits for another driver's converge before refusing.
#: A converge that changes nothing finishes in seconds; one that adds tables
#: retries each busy table for a few seconds at most.
LOCK_WAIT_SECONDS = 120.0

#: Pause between attempts to take the lock.
POLL_SECONDS = 0.5

_APPLICATION_PREFIX = "yoke-release-start:"


class ConvergenceLockHeld(RuntimeError):
    """Another driver kept the convergence lock past the wait bound."""

    def __init__(self, holder: str, waited: float) -> None:
        super().__init__(
            f"another driver ({holder}) was still applying this release's "
            f"additive schema after {waited:.0f}s"
        )
        self.holder = holder


@contextmanager
def holding_convergence_lock(conn: Any, run_id: str) -> Iterator[None]:
    """Hold the convergence lock for *run_id*'s driver on *conn*'s session."""
    conn.execute(
        "SELECT set_config('application_name', %s, false)",
        (f"{_APPLICATION_PREFIX}{run_id}"[:63],),
    )
    conn.commit()
    deadline = time.monotonic() + LOCK_WAIT_SECONDS
    started = time.monotonic()
    while not _try_lock(conn):
        if time.monotonic() >= deadline:
            raise ConvergenceLockHeld(_holder(conn), time.monotonic() - started)
        time.sleep(POLL_SECONDS)
    try:
        yield
    finally:
        try:
            conn.rollback()
            conn.execute("SELECT pg_advisory_unlock(%s)", (LOCK_KEY,))
            conn.commit()
        except Exception:  # noqa: BLE001 — closing the session releases it
            pass


def _try_lock(conn: Any) -> bool:
    row = conn.execute("SELECT pg_try_advisory_lock(%s)", (LOCK_KEY,)).fetchone()
    conn.commit()
    return bool(row and row[0])


def _holder(conn: Any) -> str:
    """Name the run whose driver holds the lock, from its connection."""
    row = conn.execute(
        "SELECT a.application_name, a.pid FROM pg_locks l "
        "JOIN pg_stat_activity a ON a.pid = l.pid "
        "WHERE l.locktype = 'advisory' AND l.granted AND l.objsubid = 1 "
        "AND l.database = (SELECT oid FROM pg_database "
        "WHERE datname = current_database()) "
        "AND l.classid = %s::bigint::oid AND l.objid = %s::bigint::oid",
        ((LOCK_KEY >> 32) & 0xFFFFFFFF, LOCK_KEY & 0xFFFFFFFF),
    ).fetchone()
    conn.commit()
    if row is None:
        return "a driver that has since released it"
    name, pid = str(row[0] or ""), row[1]
    if name.startswith(_APPLICATION_PREFIX):
        return f"run {name[len(_APPLICATION_PREFIX):]}, backend pid {pid}"
    return f"backend pid {pid}"


__all__ = [
    "LOCK_KEY",
    "LOCK_WAIT_SECONDS",
    "POLL_SECONDS",
    "ConvergenceLockHeld",
    "holding_convergence_lock",
]
