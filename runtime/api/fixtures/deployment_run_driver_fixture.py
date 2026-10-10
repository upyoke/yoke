"""A live driver for seeded deployment runs.

An executing run with no live driver is finished by automatic completion as
soon as its last obligation settles. Fixtures that walk a run through several
QA writes model a run whose driver is still continuing it, so they attach one;
a test about automatic completion releases it at the point completion may run.
"""

from __future__ import annotations

from typing import Any

from yoke_core.domain.deployment_run_driver_attachment import (
    PHASE_EXECUTING,
    attach_driver,
    release_driver,
)

DRIVER_SESSION = "seeded-run-driver"
DRIVER_PID = 4242


def attach_seeded_driver(conn: Any, run_id: str) -> None:
    """Record a live driver on *run_id*; the caller commits."""
    attach_driver(
        conn,
        run_id,
        session_id=DRIVER_SESSION,
        pid=DRIVER_PID,
        phase=PHASE_EXECUTING,
    )


def release_seeded_driver(conn: Any, run_id: str) -> None:
    """Detach the seeded driver so automatic completion may finish *run_id*."""
    release_driver(conn, run_id, session_id=DRIVER_SESSION, pid=DRIVER_PID)
    conn.commit()


__all__ = [
    "DRIVER_PID",
    "DRIVER_SESSION",
    "attach_seeded_driver",
    "release_seeded_driver",
]
