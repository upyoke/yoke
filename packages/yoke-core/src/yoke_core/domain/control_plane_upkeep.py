"""Control-plane upkeep: GitHub observation, QA replays and wakes, and pruning.

It also releases lapsed Test Machine hold-overs (``qa_host_holdover``), so a
session queued behind one is served even when nobody else acquires the host,
and returns hosts held by parked or exited sessions past the machine's idle
hold to the line (``qa_host_idle_hold``), passing an away set-waiter's partial
reservations to the next waiter (``qa_host_idle_waiters``).

Merge-queue landings and session CI waits settle only when someone reads
GitHub, and a QA waiver leaves its close-out replays owed in
``qa_settlement_followups``. A deployment run whose driver exited at an
item-scoped QA wait leaves members it never woke.
:func:`run_control_plane_upkeep` does all three once, then runs the
universe's scheduled row retention when it is due
(:mod:`yoke_core.domain.universe_prune_schedule`), which keeps a receipt for
every run, refusals included.
It rides scheduled work that already runs in the one long-lived process each
install mode has: the API server's health refresh (hosted and self-hosted),
or each cycle of a machine-local universe's standing relay, which dispatches
in-process and has no server. It starts no thread of its own.

The landing cadence row and each CI wait's read stamp hold GitHub reads to
the shared poll floor however often upkeep runs, and a settlement row is
claimed before its replay, so concurrent processes never repeat work. A
failed step is logged and the next run re-derives the same work from the
same durable rows. The landing observer records its failure on the project's
refresh row, where ``landing.observe`` reports it to a waiter; a replay that
raises keeps its error on its follow-up row, which the steering report lists.
A QA wake is a stored session message keyed like the driver's own, so a
failed or repeated pass never sends one twice, and the fleet report shows
each member's wake state.
"""

from __future__ import annotations

import hashlib
import logging
from datetime import datetime
from typing import Any

from yoke_contracts.timestamps import utc_now
from yoke_core.domain.deployment_qa_driverless_wake import wake_driverless_qa_waits
from yoke_core.domain.merge_queue_landing_observer import observe_pending_landings
from yoke_core.domain.project_identity import row_value
from yoke_core.domain.qa_host_holdover import expire_holdovers
from yoke_core.domain.qa_host_idle_hold import release_idle_host_holds
from yoke_core.domain.qa_host_idle_waiters import hand_off_idle_waiter_reservations
from yoke_core.domain.qa_settlement_followups import replay_settlement_followups
from yoke_core.domain.session_ci_wait_observer import observe_pending_ci_runs
from yoke_core.domain.universe_prune_schedule import run_scheduled_prune


_LOG = logging.getLogger(__name__)


def observe_pending_github_work(
    conn: Any, *, now: datetime | None = None
) -> dict[str, Any]:
    """Run both GitHub observers over every project; one failing spares the other."""
    current = utc_now() if now is None else now
    from yoke_core.domain.project_retirement import active_projects_where

    rows = conn.execute(
        "SELECT id FROM projects" + active_projects_where(conn) + " ORDER BY id"
    ).fetchall()
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


#: Every API worker process runs the upkeep thread; one pass at a time
#: does the work. Each step is safe to repeat, so this only stops a second
#: worker from repeating the same queries and GitHub reads in the same tick.
UPKEEP_LOCK_KEY = int.from_bytes(
    hashlib.sha256(b"control-plane-upkeep").digest()[:8], "big", signed=True
)


def _sole_runner(conn: Any) -> bool:
    """Take the upkeep lock for this connection's session, or report it busy.

    :func:`_release` ends it when the pass ends, so the lock never depends
    on how the connection layer recycles the session.
    """
    from yoke_core.domain import db_backend

    if not db_backend.connection_is_postgres(conn):
        return True
    row = conn.execute(
        "SELECT pg_try_advisory_lock(%s)", (UPKEEP_LOCK_KEY,)
    ).fetchone()
    conn.commit()
    return bool(row and row[0])


def _release(conn: Any) -> None:
    # A failed step already rolled back, so the session can run the unlock.
    try:
        conn.execute("SELECT pg_advisory_unlock(%s)", (UPKEEP_LOCK_KEY,))
        conn.commit()
    except Exception:  # noqa: BLE001 - a closed session releases it too
        _LOG.warning("control-plane upkeep lock release failed", exc_info=True)


def run_control_plane_upkeep() -> None:
    """Run each upkeep step once on a fresh connection; never raises.

    Its hosts keep standing whatever happens here, and a failed step spares
    the next one.
    """
    from yoke_core.domain.db_helpers import connect

    try:
        conn = connect()
    except Exception:  # noqa: BLE001 - the next run connects again
        _LOG.warning("control-plane upkeep could not connect", exc_info=True)
        return
    locked = False
    try:
        if not _sole_runner(conn):
            return
        locked = True
        for name, step in (
            ("pending GitHub observation", observe_pending_github_work),
            ("QA settlement follow-up replay", replay_settlement_followups),
            ("driverless item-QA wake", wake_driverless_qa_waits),
            ("lapsed Test Machine hold-over release", expire_holdovers),
            ("idle parked QA host release", release_idle_host_holds),
            ("idle parked set-waiter turn handoff", hand_off_idle_waiter_reservations),
            ("scheduled universe prune", run_scheduled_prune),
        ):
            try:
                step(conn)
            except Exception:  # noqa: BLE001 - its durable rows carry it over
                _LOG.warning("%s failed", name, exc_info=True)
                try:
                    conn.rollback()
                except Exception:  # noqa: BLE001 - the warning above is the report
                    pass
    finally:
        if locked:
            _release(conn)
        conn.close()


__all__ = [
    "UPKEEP_LOCK_KEY",
    "observe_pending_github_work",
    "run_control_plane_upkeep",
]
