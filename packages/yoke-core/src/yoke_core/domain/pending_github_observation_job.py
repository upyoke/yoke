"""The background job that reads GitHub for pending landings and CI runs.

Merge-queue landings and session CI waits settle only when someone reads
GitHub. That read used to ride every relay claim, so a claim paid one GitHub
round trip per queued pull request before its long-poll even began. It runs
here instead, on its own thread, in the one long-lived process each install
mode has: the API server (hosted and self-hosted), or the standing relay of a
machine-local universe, which dispatches in-process and has no server.

Each cycle observes every project. The landing cadence row and each CI wait's
read stamp keep concurrent processes to one GitHub read per cadence. A failed
cycle is logged and the next cycle re-derives the same work from the same
durable rows; the landing observer also records its failure on the project's
refresh row, where ``landing.observe`` reports it to a waiter.
"""

from __future__ import annotations

import logging
import threading
from contextlib import contextmanager
from datetime import datetime
from typing import Any, Callable, Iterator

from yoke_contracts.timestamps import utc_now
from yoke_core.domain.github_poll_schedule import MINIMUM_POLL_INTERVAL_SECONDS
from yoke_core.domain.merge_queue_landing_observer import observe_pending_landings
from yoke_core.domain.project_identity import row_value
from yoke_core.domain.session_ci_wait_observer import observe_pending_ci_runs


_LOG = logging.getLogger(__name__)

#: One cycle per GitHub poll floor: a shorter interval would find every
#: project's cadence row not yet due and every CI wait read too recently.
OBSERVATION_INTERVAL_SECONDS = MINIMUM_POLL_INTERVAL_SECONDS


def observe_pending_github_work(
    conn: Any, *, now: datetime | None = None
) -> dict[str, Any]:
    """Run both GitHub observers over every project; one failing spares the other."""
    current = utc_now() if now is None else now
    rows = conn.execute("SELECT id FROM projects ORDER BY id").fetchall()
    conn.commit()
    projects = [int(row_value(row, "id", 0)) for row in rows]
    result: dict[str, Any] = {"projects": len(projects)}
    try:
        landings = observe_pending_landings(conn, projects, now=current)
    except Exception as exc:  # noqa: BLE001 - the refresh row records it too
        conn.rollback()
        _LOG.warning("pending landing observation failed: %s", exc)
        landings = {"error": str(exc)}
    for notice in landings.get("notice_errors") or ():
        _LOG.warning("pending landing notice failed: %s", notice)
    result["landings"] = landings
    try:
        ci_runs = observe_pending_ci_runs(conn, projects, now=current)
    except Exception as exc:  # noqa: BLE001 - the next cycle reads it again
        conn.rollback()
        _LOG.warning("pending CI run observation failed: %s", exc)
        ci_runs = {"errors": [str(exc)]}
    else:
        for error in ci_runs.get("errors") or ():
            _LOG.warning("pending CI run observation failed: %s", error)
    result["ci_runs"] = ci_runs
    return result


def run_observation_cycle() -> None:
    """Observe once on a fresh connection; a cycle that cannot run is logged."""
    from yoke_core.domain.db_helpers import connect

    try:
        conn = connect()
        try:
            observe_pending_github_work(conn)
        finally:
            conn.close()
    except Exception:  # noqa: BLE001 - one bad cycle never stops the job
        _LOG.warning("pending GitHub observation cycle failed", exc_info=True)


@contextmanager
def pending_github_observation_job(
    *,
    interval_seconds: float = OBSERVATION_INTERVAL_SECONDS,
    cycle: Callable[[], None] = run_observation_cycle,
) -> Iterator[None]:
    """Observe at a fixed cadence for the lifetime of the hosting process.

    The first cycle falls due one interval after start, so a process that
    boots and exits at once (a test client, a refused relay start) never
    reads GitHub.
    """
    stopped = threading.Event()

    def observe_until_stopped() -> None:
        while not stopped.wait(interval_seconds):
            cycle()

    worker = threading.Thread(
        target=observe_until_stopped,
        name="yoke-pending-github-observation",
        daemon=True,
    )
    worker.start()
    try:
        yield
    finally:
        stopped.set()
        # A cycle mid-way through a slow GitHub read must not hold shutdown;
        # its transaction rolls back with the connection.
        worker.join(timeout=interval_seconds)


__all__ = [
    "OBSERVATION_INTERVAL_SECONDS",
    "observe_pending_github_work",
    "pending_github_observation_job",
    "run_observation_cycle",
]
